import { useEffect } from "react";
import type { WorkbenchStore } from "../../stores/workbenchStore";

export function useUnsavedGuard(store: WorkbenchStore) {
  useEffect(() => {
    const confirm = () => !store.getState().dirty ||
      window.confirm("画布有未保存修改，离开将放弃这些修改。是否继续？");
    const guard = (event: Event) => { if (!confirm()) event.preventDefault(); };
    const unload = (event: BeforeUnloadEvent) => {
      if (store.getState().dirty) event.preventDefault();
    };
    const link = (event: MouseEvent) => {
      const anchor = event.target instanceof Element ? event.target.closest("a[href]") : null;
      if (anchor && anchor.getAttribute("href") !== window.location.href && !confirm()) {
        event.preventDefault();
        event.stopPropagation();
      }
    };
    document.addEventListener("ace:before-navigation", guard);
    document.addEventListener("click", link, true);
    window.addEventListener("beforeunload", unload);
    return () => {
      document.removeEventListener("ace:before-navigation", guard);
      document.removeEventListener("click", link, true);
      window.removeEventListener("beforeunload", unload);
    };
  }, [store]);
}
