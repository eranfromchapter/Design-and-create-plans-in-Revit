namespace ChapterHub.Core.Tests;

public static class TestPaths
{
    /// <summary>Walk up from the test binary to the repo root (the directory holding PLAN.md).</summary>
    public static readonly string RepoRoot = FindRepoRoot();

    private static string FindRepoRoot()
    {
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir is not null)
        {
            if (File.Exists(Path.Combine(dir.FullName, "PLAN.md"))) return dir.FullName;
            dir = dir.Parent;
        }
        throw new InvalidOperationException("repo root (PLAN.md) not found above " + AppContext.BaseDirectory);
    }

    public static string Contracts(params string[] parts) =>
        Path.Combine([RepoRoot, "packages", "contracts", .. parts]);
}
