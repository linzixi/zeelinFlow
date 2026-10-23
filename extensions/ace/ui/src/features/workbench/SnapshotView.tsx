import { memo, useState } from "react";
import type { Snapshot } from "../../lib/models";
import { formatTime } from "../../lib/models";
import ReportArtifact from "./ReportArtifact";

export default memo(function SnapshotView({ snapshot }: { snapshot: Snapshot }) {
  const [visibleRecords, setVisibleRecords] = useState(50);
  const [showRaw, setShowRaw] = useState(false);
  const records = snapshot.payload.records;
  return (
    <div className="snapshot-view">
      <small>
        {snapshot.kind === "node_output" ? "节点输出" : "节点输入"} ·{" "}
        {formatTime(snapshot.created_at)} · {records.length} 条记录
      </small>
      <p>{snapshot.payload.summary}</p>
      {records.slice(0, visibleRecords).map((record, index) => (
        <div className="snapshot-record" key={String(record.id ?? index)}>
          {String(record.title ?? record.summary ?? "记录")}
        </div>
      ))}
      {records.length > visibleRecords && (
        <button onClick={() => setVisibleRecords(value => value + 50)}>
          再显示50条（已显示{visibleRecords}/{records.length}）
        </button>
      )}
      {snapshot.payload.artifacts?.map((artifact, index) => (
        <ReportArtifact artifact={artifact} key={index} />
      ))}
      <details onToggle={event => setShowRaw(event.currentTarget.open)}>
        <summary>完整数据与快照校验值</summary>
        {showRaw && <>
          <small>SHA-256：{snapshot.digest}</small>
          <pre>{JSON.stringify(snapshot.payload, null, 2)}</pre>
        </>}
      </details>
    </div>
  );
});
