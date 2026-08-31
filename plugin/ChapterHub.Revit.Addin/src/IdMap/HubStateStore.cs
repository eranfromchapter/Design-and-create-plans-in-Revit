using System.Text.Json;
using Autodesk.Revit.DB;
using Autodesk.Revit.DB.ExtensibleStorage;
using ChapterHub.Core.Execution;

namespace ChapterHub.Revit.Addin.IdMap;

/// <summary>
/// HUB state persisted IN THE MODEL via Extensible Storage: project binding stamp,
/// last-committed seq, and the logical-id → ElementId map — one JSON document on a
/// DataStorage element, written inside the envelope's TransactionGroup so it commits
/// and rolls back WITH the ops (Part G; amendments revit-2/revit-3). A model restored
/// from backup therefore rolls seq and id-map back together, and hello reports the
/// model's truth.
/// </summary>
public sealed class HubStateStore : ISeqStore, IIdMapStore
{
    private static readonly Guid SchemaGuid = new("c4a97a2e-71d5-4a6e-9c0f-2b1d8f3e5a01");
    private const string FieldName = "HubStateJson";
    private const string StorageName = "ChapterHub.State";

    private sealed record State(string ProjectId, long LastCommittedSeq, Dictionary<string, long> IdMap);

    private readonly Document _doc;
    private State _state;

    public HubStateStore(Document doc)
    {
        _doc = doc;
        _state = Read(doc) ?? new State("", 0, []);
    }

    public long LastCommittedSeq => _state.LastCommittedSeq;
    public IReadOnlyDictionary<string, long> Entries => _state.IdMap;
    public string? BoundProjectId => _state.ProjectId.Length == 0 ? null : _state.ProjectId;

    public string IdMapHashHex() => ChapterHub.Core.IdMapHash.Compute(_state.IdMap);

    public ElementId? Resolve(string logicalId) =>
        _state.IdMap.TryGetValue(logicalId, out var id) ? new ElementId(id) : null;

    /// <summary>Bind the open document to a project at Commit #0 (verified before every
    /// TransactionGroup — an envelope for project X can never run in project Y's model).</summary>
    public void BindProject(string projectId)
    {
        _state = _state with { ProjectId = projectId };
        Write();
    }

    /// <summary>Called INSIDE the envelope's TransactionGroup, before Assimilate: rollback
    /// discards this write together with the ops.</summary>
    public void CommitEnvelope(long seq, IReadOnlyList<(string LogicalId, long ElementId)> delta)
    {
        var map = new Dictionary<string, long>(_state.IdMap);
        foreach (var (logicalId, elementId) in delta) map[logicalId] = elementId;
        _state = new State(_state.ProjectId, seq, map);
        Write();
    }

    private static Schema GetSchema()
    {
        var existing = Schema.Lookup(SchemaGuid);
        if (existing is not null) return existing;
        var builder = new SchemaBuilder(SchemaGuid);
        builder.SetSchemaName("ChapterHubState");
        builder.AddSimpleField(FieldName, typeof(string));
        return builder.Finish();
    }

    private static State? Read(Document doc)
    {
        var schema = GetSchema();
        var storage = new FilteredElementCollector(doc)
            .OfClass(typeof(DataStorage))
            .Cast<DataStorage>()
            .FirstOrDefault(ds => ds.Name == StorageName);
        var entity = storage?.GetEntity(schema);
        if (entity is null || !entity.IsValid()) return null;
        var json = entity.Get<string>(FieldName);
        return string.IsNullOrEmpty(json) ? null : JsonSerializer.Deserialize<State>(json);
    }

    private void Write()
    {
        var schema = GetSchema();
        var storage = new FilteredElementCollector(_doc)
            .OfClass(typeof(DataStorage))
            .Cast<DataStorage>()
            .FirstOrDefault(ds => ds.Name == StorageName);
        if (storage is null)
        {
            storage = DataStorage.Create(_doc);
            storage.Name = StorageName;
        }
        var entity = new Entity(schema);
        entity.Set(FieldName, JsonSerializer.Serialize(_state));
        storage.SetEntity(entity);
    }
}
