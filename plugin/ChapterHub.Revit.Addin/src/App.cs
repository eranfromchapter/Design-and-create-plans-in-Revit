using Autodesk.Revit.DB.Events;
using Autodesk.Revit.UI;
using ChapterHub.Revit.Addin.Execution;
using ChapterHub.Revit.Addin.IdMap;
using ChapterHub.Revit.Addin.Ops;
using ChapterHub.Revit.Addin.Transport;

namespace ChapterHub.Revit.Addin;

/// <summary>
/// Add-in entry point. Wires: ExternalEvent + EnvelopeHandler (one envelope per pass),
/// the background WSS client, and DocumentChangedWatcher (state_divergence on manual
/// edits/undo touching HUB-created elements). Configuration (gateway URL + enrollment
/// token) comes from the enrollment step in docs/MANUAL_REVIT_TEST.md.
/// </summary>
public sealed class App : IExternalApplication
{
    private WssClient? _client;
    private EnvelopeHandler? _handler;
    private DocumentChangedWatcher? _watcher;

    public Result OnStartup(UIControlledApplication application)
    {
        var configDir = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "ChapterHub");
        var config = AddinConfig.Load(Path.Combine(configDir, "config.json"));
        if (config is null)
        {
            // Not enrolled yet: stay dormant. Enrollment (docs/MANUAL_REVIT_TEST.md) writes
            // the config; the add-in activates on next start.
            return Result.Succeeded;
        }

        // MEP vocabulary + clash table enrolled beside the config (docs/MANUAL_REVIT_TEST.md).
        // A malformed catalog must not take the whole add-in offline: MEP ops then fail
        // cleanly with catalog_missing while everything else keeps working.
        AddinCatalogs catalogs;
        try
        {
            catalogs = AddinCatalogs.Load(Path.Combine(configDir, "catalogs"));
        }
        catch (Exception)
        {
            catalogs = AddinCatalogs.Empty;
        }
        _handler = new EnvelopeHandler(message => _client?.Send(message), catalogs);
        _handler.Attach(ExternalEvent.Create(_handler));

        _client = new WssClient(new WssClientOptions
        {
            GatewayUri = new Uri(config.GatewayUrl),
            Token = config.Token,
            WorkstationId = config.WorkstationId,
            PluginVersion = "0.1.0",
            PinFilePath = Path.Combine(configDir, "signing_key.pin"),
            ReadLastCommittedSeq = () => StateReader.LastCommittedSeq,
            ReadIdMapHash = () => StateReader.IdMapHash,
        }, _handler);
        _client.Start();

        _watcher = new DocumentChangedWatcher(message => _client?.Send(message));
        application.ControlledApplication.DocumentChanged += _watcher.OnDocumentChanged;
        application.ControlledApplication.DocumentOpened += OnDocumentOpened;
        return Result.Succeeded;
    }

    public Result OnShutdown(UIControlledApplication application)
    {
        if (_watcher is not null)
        {
            application.ControlledApplication.DocumentChanged -= _watcher.OnDocumentChanged;
        }
        application.ControlledApplication.DocumentOpened -= OnDocumentOpened;
        _client?.Dispose();
        return Result.Succeeded;
    }

    private void OnDocumentOpened(object? sender, DocumentOpenedEventArgs args)
    {
        // Hydrate the hello values from the model's Extensible Storage (the model's truth
        // survives restarts and backups — amendment revit-2/security-6).
        if (args.Document is null) return;
        var store = new HubStateStore(args.Document);
        StateReader.LastCommittedSeq = store.LastCommittedSeq;
        StateReader.IdMapHash = store.IdMapHashHex();
        _watcher?.TrackDocument(store);
    }

    /// <summary>Snapshot of the open model's persisted state for the network thread
    /// (which must never touch the Revit API).</summary>
    internal static class StateReader
    {
        public static long LastCommittedSeq { get; set; }
        public static string IdMapHash { get; set; } = ChapterHub.Core.IdMapHash.Compute(
            new Dictionary<string, long>());
    }
}

public sealed record AddinConfig
{
    public required string GatewayUrl { get; init; }
    public required string Token { get; init; }
    public required string WorkstationId { get; init; }

    public static AddinConfig? Load(string path)
    {
        if (!File.Exists(path)) return null;
        return System.Text.Json.JsonSerializer.Deserialize<AddinConfig>(
            File.ReadAllText(path),
            new System.Text.Json.JsonSerializerOptions { PropertyNamingPolicy = System.Text.Json.JsonNamingPolicy.SnakeCaseLower });
    }
}
