using ChapterHub.Core;
using Xunit;

namespace ChapterHub.Core.Tests;

public sealed class UnitConversionTests
{
    [Fact]
    public void Mm_to_ft_uses_the_rule_8_constant()
    {
        Assert.Equal(10.0, UnitConversion.MmToFt(3048), precision: 12);
        Assert.Equal(3048, UnitConversion.FtToMm(10.0), precision: 9);
        Assert.Equal(1.0, UnitConversion.MmToFt(304.8), precision: 12);
    }
}
