# Atlanta credentials vault

Google Workspace (Calendar/Gmail/Chat), GitHub and the ElevenLabs API key use one generic-password Keychain item:
service `io.github.bhadzhiev.atlanta.credentials`, account `Atlanta`.

The encrypted item contains versioned provider/library slots. Library identities use the existing SHA-256 of the resolved library path. Credentials are not exported in backups, diagnostics, settings, files or command arguments. A private cache lock file contains no secrets and serializes updates across app processes; thread locking protects writers within the process.

Migration is lazy on the first credential read. A missing provider slot is copied from its old Keychain item, saved in the shared item, then read back and compared before use. Legacy records are retained as recovery copies; a denied or corrupt shared item fails closed and does not fall back silently. Subsequent reads of a migrated slot do not access its legacy item. Disconnect removes only its provider/library slot using a tombstone, then deletes that legacy entry so it cannot be reimported accidentally.

During initial migration macOS may request access to the old Google/GitHub records as well as the shared Atlanta record. Afterward Always Allow applies to the shared item for that signed application identity. Ad-hoc signing still changes the identity on rebuild: consolidation does not eliminate that OS-level limitation. Stable signing remains the long-term fix.

The ElevenLabs key uses one slot for all libraries (`elevenlabs:default`) and has no legacy item. Each library keeps an `elevenlabs.json` file with no secret. The app reads Keychain at start only when this file exists.

Automated tests use memory-only credentials and cover migration verification, denied/corrupt storage, provider/library isolation, disconnect and concurrent updates. Real credentials are migrated only when the updated app accesses them, using normal macOS authorization dialogs.
