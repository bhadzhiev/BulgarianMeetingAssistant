# Supported sizes and browsers

This page records decision D01 for the browser UI of Atlanta.

## Widths

The required check covers these widths: **360, 430, 768, 1280, 1440 and 1920 px**. The check also covers every width between them, at a step of 20 or 40 px, as a person drags the window.

At every width:

- no content or function is lost,
- no controls overlap or are cut off,
- the page does not scroll sideways.

A row of tabs, a table or a group of chips can scroll sideways inside its own box. This is allowed, because the page does not move.

The desktop window has its own limit: `minWidth` 800 and `minHeight` 600 in `desktop/src-tauri/tauri.conf.json`. This limit applies to the native app only. It does not define the promise for the browser UI.

## Browsers

| Browser | Status |
| --- | --- |
| Atlanta desktop window (WKWebView, macOS) | Supported. This is the main target. |
| Safari, current macOS version | Supported |
| Chrome and Edge, current version | Supported |
| Firefox | Not checked |

## The check

1. Run Atlanta on a copy of a library. Never use the real library.
2. Take the launch token from the server log.
3. Run the check:

```
NODE_PATH=<folder with playwright> node scripts/check_layout.cjs http://127.0.0.1:8799 <token> 20
```

The script opens each main view and reports a page that scrolls sideways, or a visible control that goes out of the window. It changes nothing in the library.
