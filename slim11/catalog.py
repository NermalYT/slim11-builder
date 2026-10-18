"""Removal and tweak catalog.

Everything Slim11 can change lives here as plain data, so the GUI, the CLI and
the build engine all read the same list. Package names and registry values are
public Windows identifiers; the grouping and presets are this project's own.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Registry hives used by tweaks. HKLM paths are applied to the installed
# system; HKCU paths are written into the Default user profile, so every new
# account inherits them.
HKLM = "HKLM"
HKCU = "HKCU"


@dataclass(frozen=True)
class RegValue:
    hive: str
    key: str
    name: str
    value: int | str
    kind: str = "REG_DWORD"


@dataclass(frozen=True)
class AppGroup:
    id: str
    title: str
    description: str
    packages: tuple[str, ...]
    default: bool = True


@dataclass(frozen=True)
class FileRemoval:
    id: str
    title: str
    description: str
    paths: tuple[str, ...]
    default: bool = True
    risky: bool = False


@dataclass(frozen=True)
class Tweak:
    id: str
    title: str
    description: str
    values: tuple[RegValue, ...] = ()
    # Values that must be set inside Windows Setup (WinPE) before the
    # compatibility check runs.
    setup_values: tuple[RegValue, ...] = ()
    tasks_to_disable: tuple[str, ...] = ()
    default: bool = True


# --- Provisioned apps -------------------------------------------------------
# Matched as package-name prefixes against Get-AppxProvisionedPackage output.

APP_GROUPS: tuple[AppGroup, ...] = (
    AppGroup(
        "consumer-apps", "Consumer and promo apps",
        "News, Weather, Tips, Solitaire, Clipchamp, Office hub, Family, To Do and similar.",
        (
            "Clipchamp.Clipchamp", "Microsoft.BingNews", "Microsoft.BingWeather",
            "Microsoft.BingSearch", "Microsoft.GetHelp", "Microsoft.Getstarted",
            "Microsoft.MicrosoftOfficeHub", "Microsoft.MicrosoftSolitaireCollection",
            "Microsoft.People", "Microsoft.PowerAutomateDesktop", "Microsoft.Todos",
            "Microsoft.WindowsFeedbackHub", "Microsoft.WindowsMaps",
            "MicrosoftCorporationII.MicrosoftFamily", "Microsoft.StartExperiencesApp",
            "Microsoft.Wallet", "Microsoft.MixedReality.Portal", "Microsoft.Microsoft3DViewer",
            "Microsoft.SkypeApp", "Microsoft.Office.OneNote", "Microsoft.OfficePushNotificationUtility",
            "AppUp.IntelManagementandSecurityStatus",
        ),
    ),
    AppGroup(
        "communication", "Mail, Outlook, Teams and Phone Link",
        "Removes the built-in communication apps.",
        (
            "microsoft.windowscommunicationsapps", "Microsoft.OutlookForWindows",
            "MicrosoftTeams", "MSTeams", "Microsoft.Windows.Teams", "Microsoft.YourPhone",
            "Microsoft.Windows.CrossDevice",
        ),
    ),
    AppGroup(
        "ai", "Copilot and Cortana",
        "Removes the Copilot app and the legacy Cortana package.",
        ("Microsoft.Copilot", "Microsoft.Windows.Copilot", "Microsoft.549981C3F5F10"),
    ),
    AppGroup(
        "xbox", "Xbox apps and Game Bar",
        "Removes the Xbox app, Game Bar and Xbox sign-in components. Some games need these.",
        (
            "Microsoft.GamingApp", "Microsoft.XboxApp", "Microsoft.Xbox.TCUI",
            "Microsoft.XboxGameOverlay", "Microsoft.XboxGamingOverlay",
            "Microsoft.XboxIdentityProvider", "Microsoft.XboxSpeechToTextOverlay",
        ),
    ),
    AppGroup(
        "media", "Media Player and Movies & TV",
        "Removes the Zune-era media apps.",
        ("Microsoft.ZuneMusic", "Microsoft.ZuneVideo"),
    ),
    AppGroup(
        "utilities", "Inbox utilities",
        "Paint, Camera, Alarms, Sound Recorder, Sticky Notes, Terminal, Dev Home, Quick Assist.",
        (
            "Microsoft.MSPaint", "Microsoft.Paint", "Microsoft.WindowsCamera",
            "Microsoft.WindowsAlarms", "Microsoft.WindowsSoundRecorder",
            "Microsoft.MicrosoftStickyNotes", "Microsoft.WindowsTerminal",
            "Microsoft.Windows.DevHome", "MicrosoftCorporationII.QuickAssist",
        ),
    ),
)

# --- Files removed from the image offline ----------------------------------
# Paths are inside the install image, using forward slashes.

FILE_REMOVALS: tuple[FileRemoval, ...] = (
    FileRemoval(
        "edge", "Microsoft Edge",
        "Deletes the Edge browser folders. Install another browser afterwards.",
        (
            "/Program Files (x86)/Microsoft/Edge",
            "/Program Files (x86)/Microsoft/EdgeUpdate",
            "/Program Files (x86)/Microsoft/EdgeCore",
        ),
    ),
    FileRemoval(
        "webview2", "Edge WebView2 runtime",
        "Deletes the system WebView2 runtime. Widgets, new Outlook, Teams and some installers stop working.",
        ("/Windows/System32/Microsoft-Edge-Webview",),
        risky=True,
    ),
    FileRemoval(
        "onedrive", "OneDrive installer",
        "Deletes OneDriveSetup.exe so OneDrive is not installed for new users.",
        ("/Windows/System32/OneDriveSetup.exe", "/Windows/SysWOW64/OneDriveSetup.exe"),
    ),
)

# --- Registry and task tweaks ----------------------------------------------

_CDM = r"SOFTWARE\Microsoft\Windows\CurrentVersion\ContentDeliveryManager"
_ADV = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\Advanced"

TWEAKS: tuple[Tweak, ...] = (
    Tweak(
        "hardware-bypass", "Skip TPM, Secure Boot, CPU and RAM checks",
        "Lets Setup install on hardware that Windows 11 normally rejects.",
        values=(
            RegValue(HKLM, r"SYSTEM\Setup\MoSetup", "AllowUpgradesWithUnsupportedTPMOrCPU", 1),
            RegValue(HKCU, r"Control Panel\UnsupportedHardwareNotificationCache", "SV1", 0),
            RegValue(HKCU, r"Control Panel\UnsupportedHardwareNotificationCache", "SV2", 0),
        ),
        setup_values=tuple(
            RegValue(HKLM, r"SYSTEM\Setup\LabConfig", name, 1)
            for name in ("BypassTPMCheck", "BypassSecureBootCheck", "BypassRAMCheck",
                         "BypassCPUCheck", "BypassStorageCheck")
        ),
    ),
    Tweak(
        "local-account", "Allow a local account during setup",
        "Hides the online-account screens and sets BypassNRO. Newer builds may ignore BypassNRO.",
        values=(RegValue(HKLM, r"SOFTWARE\Microsoft\Windows\CurrentVersion\OOBE", "BypassNRO", 1),),
    ),
    Tweak(
        "ads", "Suggestions, ads and auto-installed apps",
        "Turns off Start suggestions, Spotlight extras and silent app installs.",
        values=(
            RegValue(HKLM, r"SOFTWARE\Policies\Microsoft\Windows\CloudContent", "DisableWindowsConsumerFeatures", 1),
            RegValue(HKLM, r"SOFTWARE\Policies\Microsoft\Windows\CloudContent", "DisableCloudOptimizedContent", 1),
            RegValue(HKLM, r"SOFTWARE\Policies\Microsoft\PushToInstall", "DisablePushToInstall", 1),
            RegValue(HKCU, r"SOFTWARE\Policies\Microsoft\Windows\CloudContent", "DisableWindowsSpotlightFeatures", 1),
            RegValue(HKCU, r"SOFTWARE\Policies\Microsoft\Windows\CloudContent", "DisableTailoredExperiencesWithDiagnosticData", 1),
            *(RegValue(HKCU, _CDM, name, 0) for name in (
                "ContentDeliveryAllowed", "OemPreInstalledAppsEnabled", "PreInstalledAppsEnabled",
                "SilentInstalledAppsEnabled", "SoftLandingEnabled", "SubscribedContentEnabled",
                "SystemPaneSuggestionsEnabled",
            )),
            RegValue(HKCU, _ADV, "ShowSyncProviderNotifications", 0),
        ),
    ),
    Tweak(
        "telemetry", "Reduce telemetry",
        "Sets diagnostic data to the minimum allowed level and disables the advertising ID "
        "and common telemetry scheduled tasks.",
        values=(
            RegValue(HKLM, r"SOFTWARE\Policies\Microsoft\Windows\DataCollection", "AllowTelemetry", 1),
            RegValue(HKLM, r"SOFTWARE\Policies\Microsoft\Windows\AdvertisingInfo", "DisabledByGroupPolicy", 1),
            RegValue(HKCU, r"SOFTWARE\Microsoft\Windows\CurrentVersion\AdvertisingInfo", "Enabled", 0),
            RegValue(HKCU, r"SOFTWARE\Microsoft\InputPersonalization", "RestrictImplicitInkCollection", 1),
            RegValue(HKCU, r"SOFTWARE\Microsoft\InputPersonalization", "RestrictImplicitTextCollection", 1),
        ),
        tasks_to_disable=(
            r"\Microsoft\Windows\Application Experience\Microsoft Compatibility Appraiser",
            r"\Microsoft\Windows\Application Experience\ProgramDataUpdater",
            r"\Microsoft\Windows\Customer Experience Improvement Program\Consolidator",
            r"\Microsoft\Windows\Customer Experience Improvement Program\UsbCeip",
            r"\Microsoft\Windows\Windows Error Reporting\QueueReporting",
        ),
    ),
    Tweak(
        "copilot", "Turn off Copilot and Recall analysis",
        "Applies the Copilot and AI data-analysis policies and hides the taskbar button.",
        values=(
            RegValue(HKLM, r"SOFTWARE\Policies\Microsoft\Windows\WindowsCopilot", "TurnOffWindowsCopilot", 1),
            RegValue(HKLM, r"SOFTWARE\Policies\Microsoft\Windows\WindowsAI", "DisableAIDataAnalysis", 1),
            RegValue(HKCU, r"SOFTWARE\Policies\Microsoft\Windows\WindowsCopilot", "TurnOffWindowsCopilot", 1),
            RegValue(HKCU, _ADV, "ShowCopilotButton", 0),
        ),
    ),
    Tweak(
        "widgets-chat", "Turn off Widgets and Chat",
        "Disables News and Interests and the taskbar Chat icon.",
        values=(
            RegValue(HKLM, r"SOFTWARE\Policies\Microsoft\Dsh", "AllowNewsAndInterests", 0),
            RegValue(HKLM, r"SOFTWARE\Policies\Microsoft\Windows\Windows Chat", "ChatIcon", 3),
            RegValue(HKLM, r"SOFTWARE\Policies\Microsoft\Teams", "DisableInstallation", 1),
            RegValue(HKCU, _ADV, "TaskbarMn", 0),
        ),
    ),
    Tweak(
        "search", "Local-only Start search",
        "Removes web results and search highlights from Start search.",
        values=(
            RegValue(HKLM, r"SOFTWARE\Policies\Microsoft\Windows\Windows Search", "AllowCloudSearch", 0),
            RegValue(HKLM, r"SOFTWARE\Policies\Microsoft\Windows\Windows Search", "EnableDynamicContentInWSB", 0),
            RegValue(HKCU, r"SOFTWARE\Policies\Microsoft\Windows\Explorer", "DisableSearchBoxSuggestions", 1),
        ),
    ),
    Tweak(
        "onedrive-policy", "Block OneDrive sync",
        "Sets the policy that prevents OneDrive from syncing files.",
        values=(RegValue(HKLM, r"SOFTWARE\Policies\Microsoft\Windows\OneDrive", "DisableFileSyncNGSC", 1),),
    ),
    Tweak(
        "edge-policy", "Quiet Edge first run",
        "Skips Edge's first-run wizard and sidebar if Edge is kept or reinstalled.",
        values=(
            RegValue(HKLM, r"SOFTWARE\Policies\Microsoft\Edge", "HideFirstRunExperience", 1),
            RegValue(HKLM, r"SOFTWARE\Policies\Microsoft\Edge", "HubsSidebarEnabled", 0),
        ),
    ),
    Tweak(
        "reserved-storage", "Disable reserved storage",
        "Frees the space Windows reserves for updates.",
        values=(RegValue(HKLM, r"SOFTWARE\Microsoft\Windows\CurrentVersion\ReserveManager", "ShippedWithReserves", 0),),
    ),
    Tweak(
        "device-encryption", "Prevent automatic device encryption",
        "Stops BitLocker device encryption from turning on by itself.",
        values=(RegValue(HKLM, r"SYSTEM\CurrentControlSet\Control\BitLocker", "PreventDeviceEncryption", 1),),
    ),
)


@dataclass
class Selection:
    """What a build removes and changes."""

    apps: list[str] = field(default_factory=list)       # AppGroup ids
    files: list[str] = field(default_factory=list)      # FileRemoval ids
    tweaks: list[str] = field(default_factory=list)     # Tweak ids
    extra_packages: list[str] = field(default_factory=list)

    def validate(self) -> None:
        for kind, chosen, known in (
            ("app group", self.apps, APP_GROUPS),
            ("file removal", self.files, FILE_REMOVALS),
            ("tweak", self.tweaks, TWEAKS),
        ):
            ids = {item.id for item in known}
            unknown = [c for c in chosen if c not in ids]
            if unknown:
                raise ValueError(f"Unknown {kind}: {', '.join(unknown)}")

    def packages(self) -> list[str]:
        out: list[str] = []
        for group in APP_GROUPS:
            if group.id in self.apps:
                out.extend(group.packages)
        out.extend(p.strip() for p in self.extra_packages if p.strip())
        return sorted(set(out), key=out.index)

    def file_paths(self) -> list[str]:
        return [p for r in FILE_REMOVALS if r.id in self.files for p in r.paths]

    def chosen_tweaks(self) -> list[Tweak]:
        return [t for t in TWEAKS if t.id in self.tweaks]


def preset(name: str) -> Selection:
    """Built-in starting points. Custom starts empty."""
    if name == "slim":
        return Selection(
            apps=[g.id for g in APP_GROUPS if g.default],
            files=[f.id for f in FILE_REMOVALS if f.default and not f.risky],
            tweaks=[t.id for t in TWEAKS if t.default],
        )
    if name == "light":
        return Selection(
            apps=["consumer-apps", "ai"],
            tweaks=["hardware-bypass", "local-account", "ads", "copilot", "search"],
        )
    if name == "custom":
        return Selection()
    raise ValueError(f"Unknown preset: {name}")


PRESETS = (
    ("slim", "Slim", "Tiny11-style: removes bundled apps, Edge and OneDrive, applies all tweaks. "
                     "Keeps Windows Update, Defender, Store and recovery."),
    ("light", "Light", "Removes promo apps and Copilot, skips hardware checks. Keeps Edge, OneDrive and utilities."),
    ("custom", "Custom", "Start with nothing selected and pick each item."),
)


def as_dict() -> dict:
    """Catalog in a JSON-friendly shape for the GUI."""
    return {
        "presets": [{"id": i, "title": t, "description": d, "selection": preset(i).__dict__} for i, t, d in PRESETS],
        "apps": [{"id": g.id, "title": g.title, "description": g.description, "packages": list(g.packages)}
                 for g in APP_GROUPS],
        "files": [{"id": f.id, "title": f.title, "description": f.description, "risky": f.risky}
                  for f in FILE_REMOVALS],
        "tweaks": [{"id": t.id, "title": t.title, "description": t.description} for t in TWEAKS],
    }
