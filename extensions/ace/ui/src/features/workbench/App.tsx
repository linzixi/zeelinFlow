import { useEffect, useMemo, useState } from "react";
import { createApi, type HostContext } from "../../lib/api";
import EditorApp from "./EditorApp";
import ReviewApp from "./ReviewApp";

export default function App({ host }: { host: HostContext }) {
  const api = useMemo(() => createApi(host), [host]);
  const [role, setRole] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    void api.access().then(value => { if (active) setRole(value.role); })
      .catch((reason: Error) => { if (active) setError(reason.message); });
    return () => { active = false; };
  }, [api]);
  if (error) return <div className="ace-app"><p role="alert">{error}</p></div>;
  if (!role) return <div className="ace-app"><p role="status">正在读取工作台权限…</p></div>;
  if (role === "reviewer") return <ReviewApp api={api} />;
  if (!/^\/workspace\/projects\/[^/]+/.test(window.location.pathname))
    return <div className="ace-app"><div className="empty-state"><h2>画布已归属到项目</h2><p>请进入团队项目，在项目内建立和编辑画布。</p><a href="/workspace/projects">打开项目与画布</a></div></div>;
  return <EditorApp host={host} />;
}
