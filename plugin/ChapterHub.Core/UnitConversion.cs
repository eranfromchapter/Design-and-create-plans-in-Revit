namespace ChapterHub.Core;

/// <summary>Rule 8: all contract coordinates are millimeters; Revit internal units are feet.</summary>
public static class UnitConversion
{
    public const double MmPerFoot = 304.8;

    public static double MmToFt(double mm) => mm / MmPerFoot;

    public static double FtToMm(double ft) => ft * MmPerFoot;
}
