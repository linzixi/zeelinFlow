interface Visibility {
  visible(): boolean;
  subscribe(listener: () => void): () => void;
}

const browserVisibility: Visibility = {
  visible: () => document.visibilityState !== "hidden",
  subscribe: listener => {
    document.addEventListener("visibilitychange", listener);
    return () => document.removeEventListener("visibilitychange", listener);
  },
};

/** Schedule after completion, so slow requests never accumulate or poll hidden tabs. */
export function startPolling(
  load: () => Promise<void>,
  interval: number,
  visibility: Visibility = browserVisibility,
) {
  let stopped = false;
  let running = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  async function tick() {
    if (stopped || running || !visibility.visible()) return;
    running = true;
    try {
      await load();
    } finally {
      running = false;
      if (!stopped && visibility.visible()) timer = setTimeout(() => void tick(), interval);
    }
  }
  const unsubscribe = visibility.subscribe(() => {
    clearTimeout(timer);
    void tick();
  });
  void tick();
  return () => {
    stopped = true;
    clearTimeout(timer);
    unsubscribe();
  };
}
