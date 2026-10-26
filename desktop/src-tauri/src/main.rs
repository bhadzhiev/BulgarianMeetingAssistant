#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::{io::{BufRead, BufReader, Write}, path::PathBuf, process::{Child, Command, Stdio},
    sync::{Arc, Mutex, atomic::{AtomicBool, Ordering}}, thread, time::{Duration, Instant}};
use std::os::unix::process::CommandExt;
use tauri::{Manager, RunEvent, WindowEvent};
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons};
use tauri::menu::{Menu, MenuItem};

#[derive(Default)]
struct Backend { child: Mutex<Option<Child>>, quitting: AtomicBool, stopped: AtomicBool,
    recording: AtomicBool, confirming: AtomicBool, exit_confirmed: AtomicBool }

fn status(app: &tauri::AppHandle, message: &str) {
    if let Some(window) = app.get_webview_window("main") {
        let encoded = serde_json::to_string(message).unwrap();
        let _ = window.eval(format!("document.getElementById('status')?.replaceChildren(document.createTextNode({encoded}))"));
        let _ = window.eval(format!("window.dispatchEvent(new CustomEvent('desktop-status', {{detail: {encoded}}}))"));
        let _ = window.set_title(message);
    }
}

fn start(app: tauri::AppHandle, state: Arc<Backend>) -> Result<(), String> {
    let data = std::env::var_os("BMA_DATA_DIR").map(PathBuf::from)
        .unwrap_or(app.path().app_data_dir().map_err(|e| e.to_string())?);
    std::fs::create_dir_all(&data).map_err(|e| e.to_string())?;
    let resources = app.path().resource_dir().map_err(|e| e.to_string())?;
    let mut command;
    if let Some(root) = std::env::var_os("BMA_DEV_ROOT") {
        let root = PathBuf::from(root);
        let python = std::env::var_os("BMA_PYTHON").map(PathBuf::from).unwrap_or(root.join(".venv/bin/python"));
        command = Command::new(python);
        command.arg(root.join("desktop_app.py")).current_dir(root);
    } else {
        command = Command::new(resources.join("backend/meeting-backend/meeting-backend"));
    }
    let log_path = data.join("backend.log");
    if log_path.metadata().map(|m| m.len() > 10_000_000).unwrap_or(false) {
        std::fs::rename(&log_path, data.join("backend.previous.log")).map_err(|e| e.to_string())?;
    }
    let log = std::fs::OpenOptions::new().create(true).append(true).open(log_path).map_err(|e| e.to_string())?;
    // A private pipe controls only this child. EOF also shuts it down if the native process dies.
    command.args(["--desktop-control", "--no-browser", "--port", "8765", "--library"])
        .arg(data.join("meetings")).arg("--models").arg(data.join("models"))
        .stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(log).process_group(0);
    let mut owned = state.child.lock().unwrap();
    if state.quitting.load(Ordering::SeqCst) { return Ok(()); }
    let mut child = command.spawn().map_err(|e| format!("Cannot start the local server: {e}"))?;
    let stdout = child.stdout.take().ok_or("Cannot read server startup")?;
    *owned = Some(child);
    drop(owned);
    let (sender, receiver) = std::sync::mpsc::channel();
    let control_state = state.clone();
    let control_app = app.clone();
    thread::spawn(move || {
        // Continue draining stdout after readiness so verbose libraries cannot fill the pipe.
        for line in BufReader::new(stdout).lines().map_while(Result::ok) {
            if let Ok(value) = serde_json::from_str::<serde_json::Value>(&line) {
                if value["event"] == "ready" {
                    let _ = sender.send(value["url"].as_str().unwrap_or("").to_owned());
                } else if value["event"] == "recording" {
                    let active = value["active"].as_bool().unwrap_or(false);
                    control_state.recording.store(active, Ordering::SeqCst);
                    if !active {
                        if let Some(window) = control_app.get_webview_window("main") {
                            let _ = window.request_user_attention(None);
                            if !control_state.quitting.load(Ordering::SeqCst) { let _ = window.set_title("Atlanta"); }
                        }
                    }
                } else if value["event"] == "microphone" {
                    if let Some(window) = control_app.get_webview_window("main") {
                        let missing = value["missing"].as_bool().unwrap_or(false);
                        let _ = window.set_title(if missing { "Microphone unavailable — recording has gaps" } else { "Atlanta" });
                        let _ = window.request_user_attention(if missing { Some(tauri::UserAttentionType::Critical) } else { None });
                    }
                }
            }
        }
    });
    let url = receiver.recv_timeout(Duration::from_secs(40)).map_err(|_| "The local server did not start. Check backend.log in Application Support. Another app may be using port 8765.")?;
    let url: tauri::Url = url.parse().map_err(|_| "Invalid server address")?;
    if url.scheme() != "http" || url.host_str() != Some("127.0.0.1") || url.port() != Some(8765) {
        return Err("The server returned an unexpected address".into());
    }
    if !state.quitting.load(Ordering::SeqCst) {
        let window = app.get_webview_window("main").ok_or("Window closed")?;
        window.navigate(url).map_err(|e| e.to_string())?;
        let _ = window.set_title("Atlanta");
    }
    thread::spawn(move || {
        while !state.quitting.load(Ordering::SeqCst) {
            let stopped = state.child.lock().unwrap().as_mut()
                .map(|child| matches!(child.try_wait(), Ok(Some(_)))).unwrap_or(true);
            if stopped {
                state.recording.store(false, Ordering::SeqCst);
                status(&app, "The local server stopped. Restart the app.");
                if let Some(window) = app.get_webview_window("main") {
                    let _ = window.request_user_attention(Some(tauri::UserAttentionType::Critical));
                }
                break;
            }
            thread::sleep(Duration::from_millis(500));
        }
    });
    Ok(())
}

fn stop(state: &Backend) {
    let child = state.child.lock().unwrap().take();
    if let Some(mut child) = child {
        if let Some(mut input) = child.stdin.take() { let _ = input.write_all(b"shutdown\n"); }
        let deadline = Instant::now() + Duration::from_secs(90);
        loop {
            if matches!(child.try_wait(), Ok(Some(_))) { break; }
            if Instant::now() >= deadline {
                // Last resort, scoped to the process group created above, never a port/PID search.
                unsafe { libc::kill(-(child.id() as i32), libc::SIGKILL); }
                let _ = child.wait();
                break;
            }
            thread::sleep(Duration::from_millis(100));
        }
    }
}

fn main() {
    let state = Arc::new(Backend::default());
    let startup = state.clone();
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _, _| {
            if let Some(window) = app.get_webview_window("main") { let _ = window.show(); let _ = window.set_focus(); }
        }))
        .plugin(tauri_plugin_dialog::init())
        .menu(|app| {
            let menu = Menu::default(app)?;
            // Tauri's macOS default app submenu ends with the OS Quit item.
            // Its terminate: action bypasses ExitRequested; use our own action.
            // https://github.com/tauri-apps/tauri/issues/9198
            if let Some(app_menu) = menu.items()?.first().and_then(|item| item.as_submenu()) {
                let last = app_menu.items()?.len().saturating_sub(1);
                app_menu.remove_at(last)?;
                app_menu.append(&MenuItem::with_id(app, "safe-quit", "Quit Atlanta", true, Some("Cmd+Q"))?)?;
            }
            Ok(menu)
        })
        .on_menu_event(|app, event| {
            if event.id().as_ref() == "safe-quit" { app.exit(0); }
        })
        .setup(move |app| {
            let handle = app.handle().clone();
            let state = startup.clone();
            thread::spawn(move || {
                if let Err(error) = start(handle.clone(), state.clone()) {
                    stop(&state);
                    status(&handle, &error);
                }
            });
            Ok(())
        })
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { api, .. } = event { api.prevent_close(); window.app_handle().exit(0); }
        })
        .build(tauri::generate_context!()).expect("Cannot create the desktop window")
        .run(move |app, event| {
            if let RunEvent::ExitRequested { api, .. } = event {
                if state.stopped.load(Ordering::SeqCst) { return; }
                api.prevent_exit();
                if state.recording.load(Ordering::SeqCst) && !state.exit_confirmed.load(Ordering::SeqCst)
                    && !state.quitting.load(Ordering::SeqCst) {
                    if !state.confirming.swap(true, Ordering::SeqCst) {
                        let state = state.clone(); let app = app.clone();
                        let dialog = app.dialog().message("A meeting is being recorded. Quitting stops and saves the recording.")
                            .title("Stop recording and quit?")
                            .buttons(MessageDialogButtons::OkCancelCustom("Stop & quit".into(), "Keep recording".into()));
                        let dialog = if let Some(window) = app.get_webview_window("main") { dialog.parent(&window) } else { dialog };
                        dialog.show(move |confirmed| {
                            state.confirming.store(false, Ordering::SeqCst);
                            if confirmed { state.exit_confirmed.store(true, Ordering::SeqCst); app.exit(0); }
                        });
                    }
                    return;
                }
                if !state.quitting.swap(true, Ordering::SeqCst) {
                    status(app, "Saving recording and closing…");
                    let state = state.clone(); let app = app.clone();
                    thread::spawn(move || { stop(&state); state.stopped.store(true, Ordering::SeqCst); app.exit(0); });
                }
            }
        });
}
