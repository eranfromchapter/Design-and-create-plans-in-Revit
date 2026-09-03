using System.Text.Json;
using ChapterHub.Core;
using ChapterHub.Core.Contracts;
using Xunit;

namespace ChapterHub.Core.Tests;

/// <summary>Phase 7 pure parts of the executor: content-addressed refs, the export plan and
/// its wire frame, the blob upload URL, the set_parameter allowlist + category + storage rules.</summary>
public sealed class BlobRefTests
{
    [Fact]
    public void Of_is_lowercase_sha256_hex_known_vector() =>
        Assert.Equal("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad", BlobRef.Of("abc"u8));

    [Fact]
    public void Of_empty_is_the_empty_hash() =>
        Assert.Equal("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", BlobRef.Of(ReadOnlySpan<byte>.Empty));

    [Theory]
    [InlineData("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad", true)]
    [InlineData("BA7816BF8F01CFEA414140DE5DAE2223B00361A396177A9CB410FF61F20015AD", false)]
    [InlineData("ba7816bf", false)]
    [InlineData("", false)]
    [InlineData(null, false)]
    [InlineData("../etc/passwd", false)]
    public void IsValid_pins_the_pattern(string? candidate, bool expected) => Assert.Equal(expected, BlobRef.IsValid(candidate));
}

public sealed class ExportPlanTests
{
    private static ExportViewsArgs Args(params (string Name, string Kind, int Px)[] views) => new()
    {
        Views = views.Select(v => new ViewSpec { Name = v.Name, Kind = v.Kind, Px = v.Px }).ToList(),
    };

    [Fact]
    public void Frames_keep_the_views_order_and_index()
    {
        var frames = ExportPlan.From(Args(("plan", "plan", 2048), ("section", "section", 2048), ("3d_hidden", "3d_hidden", 1024)));
        Assert.Equal([0, 1, 2], frames.Select(f => f.Index));
        Assert.Equal(["plan", "section", "3d_hidden"], frames.Select(f => f.Name));
        Assert.Equal(1024, frames[2].Px);
    }

    [Fact]
    public void Unknown_kind_and_px_bounds_are_refused()
    {
        Assert.Throws<ArgumentException>(() => ExportPlan.From(Args(("x", "elevation", 2048))));
        Assert.Throws<ArgumentException>(() => ExportPlan.From(Args(("x", "plan", 100))));
        Assert.Throws<ArgumentException>(() => ExportPlan.From(Args(("x", "plan", 5000))));
    }

    [Fact]
    public void Ready_message_carries_no_view_name()
    {
        var reference = BlobRef.Of("png"u8);
        var json = ExportPlan.ReadyMessageJson(reference);
        using var doc = JsonDocument.Parse(json);
        var root = doc.RootElement;
        Assert.Equal(3, root.EnumerateObject().Count());
        Assert.Equal("export_ready", root.GetProperty("type").GetString());
        Assert.Equal("view", root.GetProperty("kind").GetString());
        Assert.Equal(reference, root.GetProperty("blob_ref").GetString());
        Assert.False(root.TryGetProperty("name", out _));
        Assert.False(root.TryGetProperty("envelope_id", out _));
    }

    [Fact]
    public void Ready_message_refuses_a_malformed_ref() =>
        Assert.Throws<ArgumentException>(() => ExportPlan.ReadyMessage("not-a-ref"));
}

public sealed class GatewayUrlsTests
{
    private const string Project = "1f6b3c58-7a2d-4e90-9c41-2b8f5d6a7e01";
    private static readonly string Ref = BlobRef.Of("png"u8);

    [Fact]
    public void Wss_becomes_https_and_wss_path_is_stripped() =>
        Assert.Equal(
            $"https://hub.example.com/projects/{Project}/blobs/{Ref}",
            GatewayUrls.BlobUploadUri(new Uri("wss://hub.example.com/wss"), Project, Ref).ToString());

    [Fact]
    public void Ws_becomes_http_and_the_port_survives() =>
        Assert.Equal(
            $"http://127.0.0.1:8787/projects/{Project}/blobs/{Ref}",
            GatewayUrls.BlobUploadUri(new Uri("ws://127.0.0.1:8787/wss"), Project, Ref).ToString());

    [Fact]
    public void A_path_prefix_is_kept() =>
        Assert.Equal(
            $"https://hub.example.com/gateway/projects/{Project}/blobs/{Ref}",
            GatewayUrls.BlobUploadUri(new Uri("wss://hub.example.com/gateway/wss?x=1"), Project, Ref).ToString());

    [Fact]
    public void Other_schemes_bad_refs_and_bad_ids_are_refused()
    {
        Assert.Throws<ArgumentException>(() => GatewayUrls.BlobUploadUri(new Uri("https://hub.example.com/wss"), Project, Ref));
        Assert.Throws<ArgumentException>(() => GatewayUrls.BlobUploadUri(new Uri("wss://hub.example.com/wss"), Project, "nope"));
        Assert.Throws<ArgumentException>(() => GatewayUrls.BlobUploadUri(new Uri("wss://hub.example.com/wss"), "../x", Ref));
    }
}

public sealed class ParamAllowlistTests
{
    private static readonly ParamAllowlist Allowlist =
        ParamAllowlist.FromJson(File.ReadAllText(TestPaths.Contracts("ops", "param_allowlist.json")));

    [Fact]
    public void The_five_chapter_params_and_comments_are_listed()
    {
        foreach (var name in new[] { "CHPT_Finish_Material", "CHPT_Finish_Color", "CHPT_Product_SKU", "CHPT_Spec_Section", "CHPT_Render_Ref", "Comments" })
            Assert.True(Allowlist.Contains(name), name);
        Assert.Equal("1.0", Allowlist.AllowlistVersion);
    }

    [Theory]
    [InlineData("CHPT_Product_SKU", "walls", true)]
    [InlineData("CHPT_Product_SKU", "plumbing", true)]
    [InlineData("CHPT_Finish_Material", "walls", true)]
    [InlineData("CHPT_Finish_Material", "doors", false)]
    [InlineData("CHPT_Finish_Material", "plumbing", false)]
    [InlineData("CHPT_Render_Ref", "casework", true)]
    [InlineData("CHPT_Render_Ref", "electrical", false)]
    [InlineData("Comments", null, true)]
    [InlineData("Comments", "walls", true)]
    [InlineData("CHPT_Product_SKU", null, false)]
    [InlineData("Mark", "walls", false)]
    [InlineData("Phase Demolished", "walls", false)]
    public void IsAllowed_by_name_then_category(string param, string? category, bool expected) =>
        Assert.Equal(expected, Allowlist.IsAllowed(param, category));

    [Fact]
    public void Text_kinds_require_strings()
    {
        Assert.True(Allowlist.RequiresString("CHPT_Product_SKU"));
        Assert.True(Allowlist.RequiresString("Comments"));
        Assert.False(Allowlist.RequiresString("Mark"));
        Assert.Equal("spec", Allowlist.Kind("CHPT_Spec_Section"));
        Assert.Null(Allowlist.Kind("Mark"));
    }

    [Fact]
    public void Plumbing_implies_furniture_the_gateway_prefix_rule_depends_on_it()
    {
        foreach (var entry in Allowlist.Entries)
            if (entry.Categories.Contains("plumbing"))
                Assert.Contains("furniture", entry.Categories);
    }

    [Fact]
    public void Unknown_category_vocabulary_is_refused_at_load() =>
        Assert.Throws<JsonException>(() => ParamAllowlist.FromJson(
            """{"allowlist_version":"x","params":[{"name":"A","kind":"finish","categories":["roofs"]}]}"""));
}

public sealed class ParamCategoriesTests
{
    [Theory]
    [InlineData("OST_Walls", "walls")]
    [InlineData("OST_Doors", "doors")]
    [InlineData("OST_Windows", "windows")]
    [InlineData("OST_Casework", "casework")]
    [InlineData("OST_PlumbingFixtures", "plumbing")]
    [InlineData("OST_ElectricalFixtures", "electrical")]
    [InlineData("OST_LightingDevices", "electrical")]
    [InlineData("OST_ElectricalEquipment", "electrical")]
    [InlineData("OST_Furniture", "furniture")]
    [InlineData("OST_FurnitureSystems", "furniture")]
    [InlineData("OST_SpecialityEquipment", "furniture")]
    [InlineData("OST_PipeCurves", null)]
    [InlineData("OST_Conduit", null)]
    [InlineData("OST_Levels", null)]
    [InlineData("OST_Rooms", null)]
    [InlineData("", null)]
    [InlineData(null, null)]
    public void Vocabulary_word_per_built_in_category(string? name, string? expected) =>
        Assert.Equal(expected, ParamCategories.Vocabulary(name));

    [Fact]
    public void Every_word_is_in_the_allowlist_vocabulary()
    {
        foreach (var name in new[] { "OST_Walls", "OST_Doors", "OST_Windows", "OST_Casework", "OST_PlumbingFixtures", "OST_ElectricalFixtures", "OST_Furniture" })
            Assert.Contains(ParamCategories.Vocabulary(name)!, ParamAllowlist.Vocabulary);
    }
}

public sealed class ParamValueCoercionTests
{
    private static JsonElement J(string json) => JsonDocument.Parse(json).RootElement.Clone();

    [Fact]
    public void Strings_take_text_numbers_and_booleans_as_text()
    {
        Assert.Equal(ParamValueCoercion.Decision.String("CHPT-WALL-PAINT-STD_PLACEHOLDER"), ParamValueCoercion.Decide(J("\"CHPT-WALL-PAINT-STD_PLACEHOLDER\""), "String"));
        Assert.Equal(ParamValueCoercion.Decision.String("12.5"), ParamValueCoercion.Decide(J("12.5"), "String"));
        Assert.Equal(ParamValueCoercion.Decision.String("true"), ParamValueCoercion.Decide(J("true"), "String"));
        Assert.Equal(ParamValueCoercion.Kind.Reject, ParamValueCoercion.Decide(J("null"), "String").Kind);
        Assert.Equal(ParamValueCoercion.Kind.Reject, ParamValueCoercion.Decide(J("{\"a\":1}"), "String").Kind);
    }

    [Fact]
    public void Doubles_take_numbers_only_no_unit_conversion()
    {
        Assert.Equal(ParamValueCoercion.Decision.Double(2.5), ParamValueCoercion.Decide(J("2.5"), "Double"));
        Assert.Equal(ParamValueCoercion.Kind.Reject, ParamValueCoercion.Decide(J("\"2.5\""), "Double").Kind);
        Assert.Equal(ParamValueCoercion.Kind.Reject, ParamValueCoercion.Decide(J("true"), "Double").Kind);
    }

    [Fact]
    public void Integers_take_whole_numbers_and_booleans_as_0_1()
    {
        Assert.Equal(ParamValueCoercion.Decision.Integer(3), ParamValueCoercion.Decide(J("3"), "Integer"));
        Assert.Equal(ParamValueCoercion.Decision.Integer(1), ParamValueCoercion.Decide(J("true"), "Integer"));
        Assert.Equal(ParamValueCoercion.Decision.Integer(0), ParamValueCoercion.Decide(J("false"), "Integer"));
        Assert.Equal(ParamValueCoercion.Kind.Reject, ParamValueCoercion.Decide(J("3.5"), "Integer").Kind);
        Assert.Equal(ParamValueCoercion.Kind.Reject, ParamValueCoercion.Decide(J("\"3\""), "Integer").Kind);
    }

    [Fact]
    public void ElementId_and_None_are_never_set()
    {
        Assert.Equal(ParamValueCoercion.Kind.Reject, ParamValueCoercion.Decide(J("3"), "ElementId").Kind);
        Assert.Equal(ParamValueCoercion.Kind.Reject, ParamValueCoercion.Decide(J("\"x\""), "None").Kind);
        Assert.Contains("never set", ParamValueCoercion.Decide(J("3"), "ElementId").Reason);
    }
}
