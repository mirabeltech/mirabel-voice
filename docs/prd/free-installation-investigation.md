Mirabel Voice — free installation investigation

**Superseded recommendation — final owner decision:** keep and improve the free Google Drive Python ZIP installation. Do not pursue Microsoft Store/MSIX, developer accounts, certification or paid signing. The research below is historical evidence, not an active implementation plan. The [release PRD](windows-release-readiness.md) and GitHub #63/#64 govern current work.

8 September 2026. Scope: investigate the easiest free distribution that works with Windows protections enabled. No Store submission, account creation, certificate purchase, production installation or security-setting change is authorized or performed here.

**Conclusion**

The best free candidate for the simplest employee experience is a Microsoft Store **MSIX** package: share a Store link, click Install, then sign in to Mirabel with the existing Google work account. It requires development work and certification before it is available. It is a feasibility recommendation, not a tested Mirabel Store release or a promise that every company policy permits it.

The fastest free route available to Mirabel today remains the **Python bundle on the shared Google Drive**, using the existing guided installation. Earlier project evidence demonstrates that this can work with Smart App Control enabled, but browser downloads can introduce a script block and the route has more steps. Keep it as the current fallback while evaluating Store packaging; do not claim it is unrestricted.

There is no installation format that guarantees execution under every Windows or company security policy. Store distribution addresses the unsigned-download problem using Microsoft's own signing/distribution path; explicit policies can still block Store access or apps. See [Microsoft's Store app troubleshooting guidance](https://learn.microsoft.com/en-us/troubleshoot/windows-client/shell-experience/error-start-store-apps).

**What changed in the recommendation**

Microsoft's current company-account onboarding is free. The May 2026 announcement removed the former company registration charge. The documented onboarding supports a personal Microsoft account as well as Entra sign-in, so a Google Workspace organization does not need to migrate email or buy an Azure signing subscription for this route. Business/domain verification is still required. Use a company publisher identity, not an individual hobbyist registration. Sources: [company registration announcement](https://blogs.windows.com/windowsdeveloper/2026/05/07/publish-to-microsoft-store-as-a-company-now-with-free-registration-and-faster-onboarding/) and [account setup](https://learn.microsoft.com/en-us/windows/apps/publish/partner-center/open-a-developer-account?tabs=company).

Microsoft provides signing, hosting and updates for MSIX packages distributed through the Store. Uploading our existing EXE installer instead does **not** get free re-signing; MSI/EXE publishers must sign their own binaries. Self-signing a downloadable installer does not give it public trust. Sources: [Store publishing](https://learn.microsoft.com/en-us/windows/apps/publish/get-started) and [Windows signing options](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/code-signing-options).

“Free” here means no Store registration, signing-certificate or distribution-service charge for the documented MSIX route. Engineering time, account verification and the existing speech-processing/cloud costs remain.

**Comparison**

| Route | Employee experience | Free? | Fit for Mirabel |
|---|---|---|---|
| Store MSIX | Open Store link, Install, Google sign-in | Documented free registration/signing/hosting | Best candidate for employee simplicity. Needs package conversion, Microsoft review and validation on Tommy's protected Windows machine. |
| Existing signed-Python ZIP | Drive download plus guided command or unblock/extract/install steps | Yes | Fastest existing route. Earlier real-download evidence required unblocking; not a guarantee against future native-library or script restrictions. |
| Unsigned EXE or an EXE wrapped in ZIP | Download/run, then possibly blocked | Yes | Ruled out by Mirabel's own Smart App Control failures. Renaming or wrapping does not change executable trust. |
| Self-signed MSIX/installer | Download plus certificate-trust setup | No certificate purchase, but manual trust work | Poor fit: shifts setup burden to employees and does not create trusted public signing. |
| Paid public signing | Download installer from Drive | No | Excluded by the current $0 requirement. Earlier claims that any paid signing service guarantees instant SmartScreen reputation should not be repeated. |

**Evidence from the existing tool**

The full comments on [issue #35](https://github.com/mirabeltech/mirabel-voice/issues/35) matter more than its initial description:

- The unsigned PyInstaller app initially ran, then was blocked when Smart App Control reevaluated it. The ZIP containing those same executables was also unsuitable.
- The Python/source bundle subsequently ran on that protected machine.
- A later genuine Drive download showed that downloaded scripts inherited the web-origin mark and were blocked. That specific test succeeded after unblocking the ZIP before extraction. Earlier locally built ZIP tests had not exercised the same download path.

This explains why a local successful launch is insufficient proof that a colleague's fresh download installs smoothly. The current builder also checks only some native signatures before installing third-party libraries; recheck the final bundle, not just the interpreter.

In this investigation, a read-only check of the connected Windows host returned Smart App Control state `1` (on) and PowerShell `FullLanguage`. No Windows protection settings were changed. The local artifact probe below does not replace a fresh browser-download test or validate the current release candidate.

**Store feasibility work required**

1. Package Mirabel as a full-trust desktop MSIX app and validate global hotkeys, tray controls, microphone/native audio libraries, clipboard injection, Tk windows and the Google browser callback. Full-trust desktop packaging is supported by MSIX; this app's behavior still needs proof. [MSIX execution model](https://learn.microsoft.com/en-us/windows/msix/msix-containerization-overview).
2. Replace source-folder self-updates for Store installations with Store-managed package updates. The current updater writes into its installed files, while MSIX application files are protected. Keep the existing approved updater only for ZIP installations. Revisit release approval, busy-update behavior and recall: a Store rollback may need a newer package containing reverted code, not our current lower-version source swap.
3. Implement package-compatible startup registration, shortcuts and version reporting; deliberately migrate existing settings and DPAPI-protected sign-in without assuming identical paths or uninstall retention.
4. Decide distribution privacy before creating a Store listing. A hidden/direct-link listing is **not private**. A private Store audience requires each recipient's personal Microsoft account in a managed list, adding work for a Google-only organization. Existing Google work sign-in should continue to authorize speech service use, but it does not make the downloadable package private. [Store visibility options](https://learn.microsoft.com/en-us/windows/apps/publish/publish-your-app/msix/visibility-options).
5. Preserve the current requirement not to publicly distribute the privately configured bundle. A broadly downloadable Store package needs an approved design for service configuration and abuse protection; do not simply upload today's bundle or treat a hidden link as security. Private Store audience is an alternative, with the account-management tradeoff above.
6. Complete business verification, package validation and certification. Prepare a privacy policy and a way for certification reviewers to exercise sign-in-dependent functionality without granting them unrestricted company access. Store approval and turnaround are not guaranteed.
7. Tommy alone validates installation from the actual Store route, startup, dictation, package update and uninstall with Smart App Control enabled. No employee pilot is required. Testing a developer-signed local MSIX does not prove the Store acquisition path.

**Decision proposed**

Prioritize a small Store-MSIX feasibility proof under issue #64, with $0 paid-service spend. Keep the Drive Python bundle as the existing installation path during investigation. Store publication and any change from private to broadly downloadable distribution remain decisions for Tommy; this investigation does not authorize either. If private delivery without Microsoft recipient accounts is essential, the current ZIP remains the practical free option, with its documented extra steps and limitations.

**Completed local artifact probe**

- Artifact: `MirabelVoice-0.7.1-python.zip`; SHA-256 `18daa9d69599d9a7247b9b35b76aee4bc68ba4f2830b13cbbdb8a88b801323c3`. This is an older local artifact, not a newly built 0.8.0 release.
- Extracted into an isolated workspace directory without running the installer or touching the existing app.
- Windows reported Smart App Control on. Of 80 EXE/DLL/PYD files, 36 had valid Authenticode signatures and 44 were unsigned, including audio and numerical-library dependencies. Not all these binaries are loaded in regular use.
- The extracted interpreter successfully imported Tkinter, NumPy, sounddevice and soundfile, and passed the audio-encoder probe (32,044 WAV bytes versus 4,152 Opus bytes for generated one-second input). No microphone recording or provider call was made.
- This proves this local artifact can load these components on this host today. It disproves the builder's blanket claim that every executable component is signed. It does not establish fresh browser-download acceptance, native dependency acceptance on other machines, future reputation, or Store-package compatibility.
