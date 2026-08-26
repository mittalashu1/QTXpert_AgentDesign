import { useEffect, useState } from "react";
import { useProjects } from "@/hooks/useProjects";

const STORAGE_KEY = "qtxpert-selected-project";
const PROJECT_EVENT = "qtxpert-project-changed";

function storedProjectId() {
  return typeof window === "undefined" ? "" : window.localStorage.getItem(STORAGE_KEY) || "";
}

export function useSelectedProject() {
  const { data: projects } = useProjects();
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
    if (!projects?.length) return;
    const currentStillExists = projects.some((project) => project.id === selectedProjectId);
    if (currentStillExists) return;
    const fallback = projects[0].id;
    window.localStorage.setItem(STORAGE_KEY, fallback);
    setSelectedProjectId(fallback);
  }, [projects, selectedProjectId]);

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
