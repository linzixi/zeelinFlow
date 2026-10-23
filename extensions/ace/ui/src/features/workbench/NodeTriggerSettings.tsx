import type { CanvasNode } from "../../lib/models";

export default function NodeTriggerSettings({ node, onChange: update }: {
  node: CanvasNode;
  onChange(changes: Partial<CanvasNode>): void;
}) {
  return (
      <section className="inspector-section">
        <h3>触发方式</h3>
        <label>
          触发类型
          <select
            value={node.trigger.kind}
            onChange={(event) =>
              update({
                trigger: {
                  ...node.trigger,
                  kind: event.target.value as CanvasNode["trigger"]["kind"],
                },
              })
            }
          >
            <option value="event">上游结果入库后</option>
            <option value="manual">手动触发</option>
            <option value="cron">定时触发</option>
          </select>
        </label>
        {node.trigger.kind === "cron" && (
          <>
            <label>
              定时运行模式
              <select
                value={node.trigger.mode ?? "simulation"}
                onChange={(event) =>
                  update({
                    trigger: { ...node.trigger, mode: event.target.value as "simulation" | "live" },
                  })
                }
              >
                <option value="simulation">模拟运行</option>
                <option value="live">正式运行</option>
              </select>
            </label>
            <label>
              常用周期
              <select
                value=""
                onChange={(event) => {
                  const presets: Record<string, [string, number]> = {
                    five: ["*/5 * * * *", 5],
                    ten: ["*/10 * * * *", 10],
                    thirty: ["*/30 * * * *", 30],
                    daily: ["0 9 * * *", 1440],
                    weekly: ["0 9 * * 1", 10080],
                    monthly: ["0 9 1 * *", 44640],
                  };
                  const preset = presets[event.target.value];
                  if (preset)
                    update({
                      trigger: {
                        ...node.trigger,
                        cron: preset[0],
                        lookbackMinutes: preset[1],
                        runAtTimes: [],
                      },
                    });
                }}
              >
                <option value="">选择执行周期</option>
                <option value="five">每5分钟 · 回看5分钟</option>
                <option value="ten">每10分钟 · 回看10分钟</option>
                <option value="thirty">每30分钟 · 回看30分钟</option>
                <option value="daily">每日 09:00 · 最近24小时</option>
                <option value="weekly">周一 09:00 · 最近7天</option>
                <option value="monthly">每月1日 09:00 · 最近31天</option>
              </select>
            </label>
            <label>
              每日固定时点
              <input
                placeholder="08:30,10:30,12:30"
                value={node.trigger.runAtTimes.join(",")}
                onChange={(event) =>
                  update({
                    trigger: {
                      ...node.trigger,
                      runAtTimes: event.target.value
                        .split(/[,，]/)
                        .map((item) => item.trim())
                        .filter(Boolean),
                    },
                  })
                }
              />
            </label>
            <label>
              Cron 表达式
              <input
                placeholder="周一 09:00：0 9 * * 1"
                value={node.trigger.cron}
                onChange={(event) =>
                  update({ trigger: { ...node.trigger, cron: event.target.value } })
                }
              />
            </label>
            <small>填写固定时点时优先使用固定时点，北京时间。</small>
            <small>到点读取回看窗口内已入库数据；下游定时节点按自己的周期执行。周期与回看范围可分别修改。</small>
            <label className="check-label">
              <input
                type="checkbox"
                checked={node.trigger.enabled}
                onChange={(event) =>
                  update({ trigger: { ...node.trigger, enabled: event.target.checked } })
                }
              />
              开启定时任务
            </label>
          </>
        )}
        <label>
          回看入库数据（分钟）
          <input
            type="number"
            min={1}
            value={node.trigger.lookbackMinutes}
            onChange={(event) =>
              update({ trigger: { ...node.trigger, lookbackMinutes: Number(event.target.value) } })
            }
          />
        </label>
      </section>
  );
}
