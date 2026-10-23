import { Download } from "lucide-react";
import type { Json } from "../../lib/models";

export default function ReportArtifact({ artifact }: { artifact: Record<string, Json> }) {
  const name = String(artifact.name ?? "报告.md");
  const content = String(artifact.content ?? "");
  const encoded = typeof artifact.content_base64 === "string" ? artifact.content_base64 : "";
  const visual = /\.(html|svg)$/i.test(name) && content;
  function download() {
    const data = encoded
      ? Uint8Array.from(atob(encoded), (character) => character.charCodeAt(0))
      : content;
    const url = URL.createObjectURL(
      new Blob([data], { type: String(artifact.mediaType ?? "text/markdown;charset=utf-8") }),
    );
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = name.replace(/[\\/:*?"<>|]/g, "_");
    anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return (
    <div className="artifact-preview">
      <h4>{name}</h4>
      <button disabled={!content && !encoded} onClick={download}>
        <Download size={14} />
        下载报告
      </button>
      {visual && <iframe className="report-document" title={name} sandbox=""
        srcDoc={'<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; img-src data:">' + content} />}
      {content && <details open={!visual && name.endsWith(".md")}>
        <summary>查看内容</summary><pre>{content}</pre>
      </details>}
    </div>
  );
}
