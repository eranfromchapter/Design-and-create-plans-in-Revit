namespace ChapterHub.Core;

/// <summary>
/// The add-in is configured with ONE gateway address — the WSS endpoint (…/wss). The Phase 7
/// blob upload rides the same host over HTTPS: wss → https, ws → http, the trailing /wss
/// stripped, then /projects/{id}/blobs/{ref}. Anything else is refused rather than guessed.
/// </summary>
public static class GatewayUrls
{
    public static Uri BlobUploadUri(Uri gatewayWss, string projectId, string blobRef)
    {
        if (!BlobRef.IsValid(blobRef)) throw new ArgumentException("blob ref must be lowercase sha256 hex", nameof(blobRef));
        if (!Guid.TryParse(projectId, out _)) throw new ArgumentException("project id must be a uuid", nameof(projectId));
        var scheme = gatewayWss.Scheme switch
        {
            "wss" => "https",
            "ws" => "http",
            _ => throw new ArgumentException($"gateway url scheme must be ws or wss, got {gatewayWss.Scheme}", nameof(gatewayWss)),
        };
        var path = gatewayWss.AbsolutePath.TrimEnd('/');
        if (path.EndsWith("/wss", StringComparison.Ordinal)) path = path[..^4];
        var builder = new UriBuilder(gatewayWss)
        {
            Scheme = scheme,
            Port = gatewayWss.IsDefaultPort ? -1 : gatewayWss.Port,
            Path = $"{path}/projects/{projectId}/blobs/{blobRef}",
            Query = "",
            Fragment = "",
        };
        return builder.Uri;
    }
}
