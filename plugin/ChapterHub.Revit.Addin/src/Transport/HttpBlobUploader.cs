using System.Net.Http.Headers;
using ChapterHub.Core;

namespace ChapterHub.Revit.Addin.Transport;

/// <summary>Phase 7: the executor stores exported bytes under their content hash BEFORE it
/// announces them (export_ready). Synchronous on purpose — the handler runs on Revit's API
/// thread inside the envelope's TransactionGroup and a failed upload must roll the envelope
/// back (blob_upload_failed), so the answer has to be known before the group assimilates.</summary>
public interface IBlobUploader
{
    bool Put(string projectId, string blobRef, byte[] bytes, out string error);
}

/// <summary>Unconfigured add-in: every export fails cleanly instead of pretending.</summary>
public sealed class NullBlobUploader : IBlobUploader
{
    public static readonly NullBlobUploader Instance = new();

    public bool Put(string projectId, string blobRef, byte[] bytes, out string error)
    {
        error = "no blob uploader configured";
        return false;
    }
}

/// <summary>PUT /projects/{id}/blobs/{ref} on the gateway's HTTPS side (GatewayUrls maps the
/// configured WSS address) under the workstation bearer. The gateway recomputes the sha256 and
/// refuses a mismatch; any non-2xx or transport failure is a failed upload.</summary>
public sealed class HttpBlobUploader(Uri gatewayWss, string token) : IBlobUploader
{
    private static readonly HttpClient Client = new() { Timeout = TimeSpan.FromSeconds(30) };
    private static readonly byte[] PngMagic = [0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A];

    public bool Put(string projectId, string blobRef, byte[] bytes, out string error)
    {
        try
        {
            using var request = new HttpRequestMessage(HttpMethod.Put, GatewayUrls.BlobUploadUri(gatewayWss, projectId, blobRef));
            request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", token);
            request.Content = new ByteArrayContent(bytes);
            request.Content.Headers.ContentType = new MediaTypeHeaderValue(
                bytes.Length >= 8 && bytes.AsSpan(0, 8).SequenceEqual(PngMagic) ? "image/png" : "application/octet-stream");
            using var response = Client.Send(request);
            if (response.IsSuccessStatusCode)
            {
                error = "";
                return true;
            }
            error = $"gateway answered {(int)response.StatusCode}";
            return false;
        }
        catch (Exception ex)
        {
            error = ex.Message;
            return false;
        }
    }
}
