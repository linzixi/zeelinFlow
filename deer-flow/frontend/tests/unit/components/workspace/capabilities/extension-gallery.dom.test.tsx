import { afterEach, expect, rs, test } from "@rstest/core";
import { cleanup, render, screen } from "@testing-library/react";

import { ExtensionGallery } from "@/components/workspace/capabilities/extension-gallery";
import { zhCN } from "@/core/i18n/locales/zh-CN";

const state = rs.hoisted(() => ({ selected: false, enabled: true }));
rs.mock("next/navigation", () => ({
  useSearchParams: () =>
    new URLSearchParams(state.selected ? "extension=example.query" : ""),
  usePathname: () => "/workspace/capabilities",
  useRouter: () => ({ replace: rs.fn() }),
}));
rs.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({ t: zhCN, locale: "zh-CN" }),
}));
rs.mock("@/core/extensions/hooks", () => ({
  useFrontendExtensions: () => ({
    data: [
      {
        namespace: "example.query",
        title: "Project data",
        description: "Project tools",
        module: null,
        entry: null,
        settings: { enabled: state.enabled },
        model_tools: [
          {
            name: "project_review_queue",
            description: "实时审核明细",
            input_schema: {
              type: "object",
              properties: { limit: { type: "integer", maximum: 50 } },
            },
          },
        ],
      },
    ],
  }),
}));
afterEach(() => {
  cleanup();
  state.selected = false;
  state.enabled = true;
});

test("operator search finds the owning extension", () => {
  render(<ExtensionGallery query="project_review_queue" />);
  expect(screen.getByText("Project data")).toBeTruthy();
  expect(screen.queryByText("Agent 团队")).toBeNull();
});

test("detail shows tool descriptions and parameters without an execution button", () => {
  state.selected = true;
  render(<ExtensionGallery />);
  expect(screen.getByText("project_review_queue")).toBeTruthy();
  expect(screen.getByText("实时审核明细")).toBeTruthy();
  expect(screen.getByText("查看参数")).toBeTruthy();
  expect(screen.getByText(/"maximum": 50/)).toBeTruthy();
  expect(screen.getByText("随扩展启用")).toBeTruthy();
  expect(screen.queryByRole("button", { name: "执行" })).toBeNull();
});

test("disabled extensions do not advertise enabled tools", () => {
  state.selected = true;
  state.enabled = false;
  render(<ExtensionGallery />);
  expect(screen.getByText("扩展未启用")).toBeTruthy();
  expect(screen.queryByText("随扩展启用")).toBeNull();
});
