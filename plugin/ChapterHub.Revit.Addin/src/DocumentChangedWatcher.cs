using Autodesk.Revit.DB.Events;
using ChapterHub.Revit.Addin.IdMap;

namespace ChapterHub.Revit.Addin;

/// <summary>
/// Detects manual edits/undo touching HUB-created elements and reports
/// state_divergence so the gateway marks the project dirty (drift gate, amendment
/// product-1/revit-8). HUB's own transactions are recognized by their Part G names
/// and skipped.
/// </summary>
public sealed class DocumentChangedWatcher(Action<object> send)
{
    private HubStateStore? _store;

    public void TrackDocument(HubStateStore store) => _store = store;

    public void OnDocumentChanged(object? sender, DocumentChangedEventArgs args)
    {
        if (_store is null) return;
        if (args.GetTransactionNames().Any(name => name.StartsWith("HUB ", StringComparison.Ordinal)))
            return; // our own executor

        var managed = new HashSet<long>(_store.Entries.Values);
        var touched = args.GetDeletedElementIds().Concat(args.GetModifiedElementIds())
            .Any(id => managed.Contains(id.Value));
        if (!touched) return;

        send(new
        {
            type = "state_divergence",
            last_valid_seq = _store.LastCommittedSeq,
            id_map_hash = _store.IdMapHashHex(),
            detail = "manual change touched HUB-managed elements",
        });
    }
}
