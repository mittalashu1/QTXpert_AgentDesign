import { useEffect, useState } from "react";
import { useProjects } from "@/hooks/useProjects";

export function useSelectedProject() {
  const { data: projects } = useProjects();
  const [selectedProjectId, setSelectedProjectId] = useState<string>(
    () => localStorage.getItem("qtxpert-selected-project") || ""
  );

  useEffect(() => {
    if (!selectedProjectId && projects && projects.length > 0) {
      setSelectedProjectId(projects[0].id);
    }
  }, [projects, selectedProjectId]);

  const selectProject = (projectId: string) => {
    setSelectedProjectId(projectId);
    localStorage.setItem("qtxpert-selected-project", projectId);
  };

  const selectedProject = projects?.find((p) => p.id === selectedProjectId) ?? null;

  return { projects: projects ?? [], selectedProjectId, selectedProject, selectProject };
}
