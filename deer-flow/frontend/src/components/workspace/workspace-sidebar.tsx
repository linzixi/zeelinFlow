"use client";

import Link from "next/link";

import {
  type Sidebar,
  SidebarHeader,
  SidebarContent,
  SidebarFooter,
  SidebarRail,
  useSidebar,
} from "@/components/ui/sidebar";
import { useThreadActivity } from "@/core/threads/activity";

import { WorkspaceChannelsList } from "./channels/workspace-channels-list";
import { PluginNavigation } from "./plugin-navigation";
import { RecentChatList } from "./recent-chat-list";
import { TeamSwitcher } from "./team-access";
import { ThreadDeleteDialogProvider } from "./thread-delete-dialog";
import { WorkspaceHeader } from "./workspace-header";
import { WorkspaceNavChatList } from "./workspace-nav-chat-list";
import { WorkspaceNavMenu } from "./workspace-nav-menu";
import {
  WorkspaceSidebarFrame,
  useWorkspaceSidebarExpanded,
} from "./workspace-sidebar-frame";

export function WorkspaceSidebar({
  ...props
}: React.ComponentProps<typeof Sidebar>) {
  // One activity poll per workspace (off unless the Gateway offers it): new
  // and changed server-created threads reach the thread lists without a
  // reload, and a read on another device clears their dots here.
  useThreadActivity();
  return (
    <ThreadDeleteDialogProvider>
      <WorkspaceSidebarFrame variant="sidebar" collapsible="icon" {...props}>
        <WorkspaceSidebarContents />
      </WorkspaceSidebarFrame>
    </ThreadDeleteDialogProvider>
  );
}

function WorkspaceSidebarContents() {
  const isSidebarOpen = useWorkspaceSidebarExpanded();
  const { isMobile } = useSidebar();
  return (
    <>
      <SidebarHeader className="py-0">
        <WorkspaceHeader />
        {isSidebarOpen && <TeamSwitcher />}
      </SidebarHeader>
      <SidebarContent>
        <WorkspaceNavChatList />
        <PluginNavigation />
        <WorkspaceChannelsList />
        {isSidebarOpen && (
          <>
            <nav
              className="flex flex-col gap-1 px-4 py-2 text-sm"
              aria-label="团队工作区"
            >
              <Link
                className="hover:bg-muted rounded p-2"
                href="/workspace/projects"
              >
                项目与画布
              </Link>
              <Link
                className="hover:bg-muted rounded p-2"
                href="/workspace/teams"
              >
                团队与成员
              </Link>
            </nav>
            <RecentChatList />
          </>
        )}
      </SidebarContent>
      <SidebarFooter>
        <WorkspaceNavMenu />
      </SidebarFooter>
      {!isMobile && <SidebarRail />}
    </>
  );
}
