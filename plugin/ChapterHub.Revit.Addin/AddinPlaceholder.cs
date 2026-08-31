namespace ChapterHub.Revit.Addin;

/// <summary>
/// Phase 0 placeholder so the solution builds end-to-end in CI. Phase 1 replaces this with:
/// Transport/ (background WSS client + enrollment), Execution/ (IExternalEventHandler, one
/// envelope per pass with its own TransactionGroup — PLAN.md Part G), Ops/ (one IOpHandler per
/// registry op), IdMap/ (Extensible Storage: logical id → ElementId + last-committed seq +
/// project binding stamp).
/// </summary>
public static class AddinPlaceholder
{
    public static string PluginVersion => "0.1.0";
}
