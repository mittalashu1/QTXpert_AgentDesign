import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { projectsApi } from "@/services/api";
import { useAuth } from "@/contexts/AuthContext";

export function useProjects() {
  const { user } = useAuth();
  return useQuery({
    // Scope the cache to the authenticated account. Without the user id, a
    // logout/login or a switch between the custom and Render domains can
    // briefly reuse another account's project list and stale selection.
    queryKey: ["projects", user?.id ?? "anonymous"],
    queryFn: () => projectsApi.list().then((res) => res.data),
    enabled: Boolean(user),
  });
}

export function useCreateProject() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ name, description }: { name: string; description?: string }) =>
      projectsApi.create(name, description).then((res) => res.data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["projects"] }),
  });
}

export function useUpdateProject() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, name, description }: { id: string; name: string; description?: string | null }) =>
      projectsApi.update(id, name, description).then((res) => res.data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["projects"] }),
  });
}
