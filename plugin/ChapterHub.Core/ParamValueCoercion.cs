using System.Globalization;
using System.Text.Json;

namespace ChapterHub.Core;

/// <summary>
/// set_parameter carries `value` as string | number | boolean; Revit stores by StorageType.
/// The executor sets exactly what the type can hold and refuses the rest (param_type_mismatch)
/// — no unit conversion in v1 (the allowlisted params are text and the odd integer flag).
/// StorageType arrives as the Revit enum NAME (String, Double, Integer, ElementId, None).
/// </summary>
public static class ParamValueCoercion
{
    public enum Kind
    {
        SetString,
        SetDouble,
        SetInteger,
        Reject,
    }

    public sealed record Decision(Kind Kind, string? StringValue, double DoubleValue, int IntegerValue, string? Reason)
    {
        public static Decision String(string value) => new(Kind.SetString, value, 0, 0, null);
        public static Decision Double(double value) => new(Kind.SetDouble, null, value, 0, null);
        public static Decision Integer(int value) => new(Kind.SetInteger, null, 0, value, null);
        public static Decision Rejected(string reason) => new(Kind.Reject, null, 0, 0, reason);
    }

    public static Decision Decide(JsonElement value, string storageType) => storageType switch
    {
        "String" => value.ValueKind switch
        {
            JsonValueKind.String => Decision.String(value.GetString()!),
            JsonValueKind.Number => Decision.String(value.GetDouble().ToString("R", CultureInfo.InvariantCulture)),
            JsonValueKind.True => Decision.String("true"),
            JsonValueKind.False => Decision.String("false"),
            _ => Decision.Rejected($"{value.ValueKind} into a String parameter"),
        },
        "Double" => value.ValueKind == JsonValueKind.Number
            ? Decision.Double(value.GetDouble())
            : Decision.Rejected($"{value.ValueKind} into a Double parameter (numbers only, no unit conversion in v1)"),
        "Integer" => value.ValueKind switch
        {
            JsonValueKind.Number when value.TryGetInt32(out var i) => Decision.Integer(i),
            JsonValueKind.Number => Decision.Rejected("non-integer number into an Integer parameter"),
            JsonValueKind.True => Decision.Integer(1),
            JsonValueKind.False => Decision.Integer(0),
            _ => Decision.Rejected($"{value.ValueKind} into an Integer parameter"),
        },
        _ => Decision.Rejected($"parameters of storage type {storageType} are never set by the HUB"),
    };
}
