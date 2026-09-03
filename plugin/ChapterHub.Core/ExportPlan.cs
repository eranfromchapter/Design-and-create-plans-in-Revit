using ChapterHub.Core.Contracts;

namespace ChapterHub.Core;

/// <summary>
/// The executor's view of an export_views op (Phase 7, P7-01): one frame per views[] entry,
/// exported and announced IN ORDER after the envelope's commit_result. The gateway
/// correlates export_ready frames by that order; the view NAME is never on the wire
/// (wss-messages export_ready is {type, kind, blob_ref} and additionalProperties:false).
/// </summary>
public static class ExportPlan
{
    public static readonly IReadOnlySet<string> Kinds = new HashSet<string> { "plan", "section", "3d_hidden" };

    public sealed record Frame(int Index, string Name, string Kind, int Px);

    /// <summary>The wire frame — serialized with ContractJson it is exactly
    /// {"blob_ref":…,"kind":"view","type":"export_ready"} (member order aside).</summary>
    public sealed record ExportReadyMessage(string Type, string Kind, string BlobRef);

    public static IReadOnlyList<Frame> From(ExportViewsArgs args)
    {
        var frames = new List<Frame>(args.Views.Count);
        for (var i = 0; i < args.Views.Count; i++)
        {
            var view = args.Views[i];
            if (!Kinds.Contains(view.Kind)) throw new ArgumentException($"unknown view kind {view.Kind}", nameof(args));
            if (view.Px is < 256 or > 4096) throw new ArgumentException($"px {view.Px} outside 256..4096", nameof(args));
            frames.Add(new Frame(i, view.Name, view.Kind, view.Px));
        }
        return frames;
    }

    public static ExportReadyMessage ReadyMessage(string blobRef)
    {
        if (!BlobRef.IsValid(blobRef)) throw new ArgumentException("blob ref must be lowercase sha256 hex", nameof(blobRef));
        return new ExportReadyMessage("export_ready", "view", blobRef);
    }

    public static string ReadyMessageJson(string blobRef) => ContractJson.Serialize(ReadyMessage(blobRef));
}
