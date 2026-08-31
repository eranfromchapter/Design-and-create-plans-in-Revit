using System.Text.Json;
using System.Text.Json.Serialization;

namespace ChapterHub.Core.Contracts;

/// <summary>2D point in millimeters, serialized as [x, y].</summary>
[JsonConverter(typeof(Pt2Converter))]
public readonly record struct Pt2(double X, double Y);

/// <summary>3D point in millimeters, serialized as [x, y, z].</summary>
[JsonConverter(typeof(Pt3Converter))]
public readonly record struct Pt3(double X, double Y, double Z);

/// <summary>[width_mm, depth_mm], both &gt; 0.</summary>
[JsonConverter(typeof(Size2Converter))]
public readonly record struct Size2(double Width, double Depth);

internal abstract class FixedNumberArrayConverter<T> : JsonConverter<T>
{
    protected abstract int Arity { get; }
    protected abstract T FromValues(double[] values);
    protected abstract double[] ToValues(T value);

    public override T Read(ref Utf8JsonReader reader, Type typeToConvert, JsonSerializerOptions options)
    {
        if (reader.TokenType != JsonTokenType.StartArray)
            throw new JsonException($"expected array of {Arity} numbers");
        var values = new double[Arity];
        for (var i = 0; i < Arity; i++)
        {
            if (!reader.Read() || reader.TokenType != JsonTokenType.Number)
                throw new JsonException($"expected array of {Arity} numbers");
            values[i] = reader.GetDouble();
        }
        if (!reader.Read() || reader.TokenType != JsonTokenType.EndArray)
            throw new JsonException($"expected exactly {Arity} numbers");
        return FromValues(values);
    }

    public override void Write(Utf8JsonWriter writer, T value, JsonSerializerOptions options)
    {
        writer.WriteStartArray();
        foreach (var v in ToValues(value)) writer.WriteNumberValue(v);
        writer.WriteEndArray();
    }
}

internal sealed class Pt2Converter : FixedNumberArrayConverter<Pt2>
{
    protected override int Arity => 2;
    protected override Pt2 FromValues(double[] v) => new(v[0], v[1]);
    protected override double[] ToValues(Pt2 p) => [p.X, p.Y];
}

internal sealed class Pt3Converter : FixedNumberArrayConverter<Pt3>
{
    protected override int Arity => 3;
    protected override Pt3 FromValues(double[] v) => new(v[0], v[1], v[2]);
    protected override double[] ToValues(Pt3 p) => [p.X, p.Y, p.Z];
}

internal sealed class Size2Converter : FixedNumberArrayConverter<Size2>
{
    protected override int Arity => 2;
    protected override Size2 FromValues(double[] v) =>
        v[0] > 0 && v[1] > 0 ? new(v[0], v[1]) : throw new JsonException("size2 members must be > 0");
    protected override double[] ToValues(Size2 s) => [s.Width, s.Depth];
}
