import { useEffect, useState } from "react";
import { useProjects } from "@/hooks/useProjects";

const STORAGE_KEY = "qtxpert-selected-project";
const PROJECT_EVENT = "qtxpert-project-changed";

function storedProjectId() {
  return typeof window === "undefined" ? "" : window.localStorage.getItem(STORAGE_KEY) || "";
}

export function useSelectedProject() {
  const { data: projects, isSuccess: projectsLoaded } = useProjects();
  const [selectedProjectId, setSelectedProjectId] = useState<string>(() => storedProjectId());

  useEffect(() => {
    const sync = () => setSelectedProjectId(storedProjectId());
    window.addEventListener(PROJECT_EVENT, sync);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener(PROJECT_EVENT, sync);
      window.removeEventListener("storage", sync);
    };
  }, []);

  useEffect(() => {
    // A project id can outlive the account/session that created it (for
    // example after switching domains or signing in as another user). Do not
    // keep sending that stale id to project-scoped endpoints: the backend
    // correctly returns 404 for an id the current user cannot access, but the
    // dashboard would otherwise surface that as a misleading data outage.
    if (!projectsLoaded || !projects) return;
    if (!projects.length) {
      if (!selectedProjectId) return;
      window.localStorage.removeItem(STORAGE_KEY);
      setSelectedProjectId("");
      window.dispatchEvent(new Event(PROJECT_EVENT));
      return;
    }
    const currentStillExists = projects.some((project) => project.id === selectedProjectId);
    if (currentStillExists) return;
    const fallback = projects[0].id;
    window.localStorage.setItem(STORAGE_KEY, fallback);
    setSelectedProjectId(fallback);
  }, [projects, projectsLoaded, selectedProjectId]);

  const selectProject = (projectId: string) => {
    if (!projectId || projectId === storedProjectId()) return;
    window.localStorage.setItem(STORAGE_KEY, projectId);
    // Local Test Design drafts are intentionally not shared across projects.
    window.localStorage.removeItem("qtxpert-saved-chats");
    window.dispatchEvent(new Event(PROJECT_EVENT));
    // A project switch is a workspace switch. Reloading guarantees that every
    // module, pending query and non-query local state is rebuilt for the new project.
    window.location.reload();
  };

  const selectedProject = projects?.find((project) => project.id === selectedProjectId) ?? null;

  return { projects: projects ?? [], selectedProjectId, selectedProject, selectProject };
}
