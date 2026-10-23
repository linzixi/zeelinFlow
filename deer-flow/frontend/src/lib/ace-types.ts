export type TeamRole = "admin" | "orchestrator" | "reviewer" | "none";
export interface Team {
  id: string;
  name: string;
  role: TeamRole;
}
export interface TeamProject {
  id: string;
  team_id: string;
  name: string;
  description: string;
}
export interface TeamMember {
  user_id: string;
  label: string;
  role: TeamRole | "disabled";
  revision: number;
}
export interface WorkspaceAccess {
  user_id: string;
  platform_admin: boolean;
  teams: Team[];
  active_team_id: string | null;
  role: TeamRole;
  permissions: string[];
  roles: Record<string, string>;
  projects: TeamProject[];
}
export interface CanvasSummary {
  id: string;
  name: string;
  revision: number;
}
