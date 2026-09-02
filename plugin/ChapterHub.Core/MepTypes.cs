using System.Text.Json;

namespace ChapterHub.Core;

/// <summary>
/// packages/contracts/catalogs/mep_types.json as the plugin sees it: the Revit names the
/// MEP handlers look up (pipe types + PipingSystemType names per system, the conduit type,
/// the electrical device families per kind). Every entry is human-supplied (Part J);
/// _PLACEHOLDER rows never ship. Loaded from the enrollment catalog directory.
/// </summary>
public sealed class MepTypes
{
    public sealed record DeviceFamily(string RevitFamily, string RevitType);

    public IReadOnlyDictionary<string, string> PipeTypes { get; }
    public IReadOnlyDictionary<string, string> SystemTypeNames { get; }
    public string ConduitType { get; }
    public double ConduitDiameterMm { get; }
    public IReadOnlyDictionary<string, DeviceFamily> DeviceFamilies { get; }

    private MepTypes(
        IReadOnlyDictionary<string, string> pipeTypes,
        IReadOnlyDictionary<string, string> systemTypeNames,
        string conduitType,
        double conduitDiameterMm,
        IReadOnlyDictionary<string, DeviceFamily> deviceFamilies)
    {
        PipeTypes = pipeTypes;
        SystemTypeNames = systemTypeNames;
        ConduitType = conduitType;
        ConduitDiameterMm = conduitDiameterMm;
        DeviceFamilies = deviceFamilies;
    }

    public static MepTypes FromJson(string json)
    {
        using var doc = JsonDocument.Parse(json);
        var root = doc.RootElement;
        return new MepTypes(
            root.GetProperty("pipe_types").EnumerateObject().ToDictionary(p => p.Name, p => p.Value.GetString()!),
            root.GetProperty("system_type_names").EnumerateObject().ToDictionary(p => p.Name, p => p.Value.GetString()!),
            root.GetProperty("conduit_type").GetString()!,
            root.GetProperty("conduit_diameter_mm").GetDouble(),
            root.GetProperty("device_families").EnumerateObject().ToDictionary(
                p => p.Name,
                p => new DeviceFamily(
                    p.Value.GetProperty("revit_family").GetString()!,
                    p.Value.GetProperty("revit_type").GetString()!)));
    }

    /// <summary>System name for a PipingSystemType (reverse of system_type_names); null when
    /// the type is not one the catalog names (existing model systems).</summary>
    public string? SystemOf(string systemTypeName) =>
        SystemTypeNames.FirstOrDefault(kv => kv.Value == systemTypeName).Key;
}
