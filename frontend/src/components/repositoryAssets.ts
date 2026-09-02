import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { uploadsApi } from "@/services/api";
import { UploadedAsset } from "@/types/domain";

export interface RepositoryAssetQueryOptions {
  projectId: string | null | undefined;
  categories?: readonly string[];
  extensions?: readonly string[];
  excludeCategories?: readonly string[];
  excludeSourceModules?: readonly string[];
  cacheKey?: string;
  enabled?: boolean;
}

function normalizedValues(values: readonly string[] | undefined) {
  return [...new Set((values || []).map((value) => value.trim().toLowerCase().replace(/^\./, "")).filter(Boolean))].sort();
}

export function repositoryAssetExtension(asset: Pick<UploadedAsset, "extension" | "filename">) {
  const declared = (asset.extension || "").trim().toLowerCase().replace(/^\./, "");
  if (declared) return declared;
  return asset.filename.split(".").pop()?.trim().toLowerCase() || "";
}

export function repositoryAssetBytes(value: number) {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  if (value < 1024 * 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
  return `${(value / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

export function repositoryAssetDate(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleDateString();
}

export function repositoryAssetMatches(
  asset: UploadedAsset,
  options: Pick<RepositoryAssetQueryOptions, "categories" | "extensions" | "excludeCategories" | "excludeSourceModules">,
) {
  const categories = new Set(normalizedValues(options.categories));
  const extensions = new Set(normalizedValues(options.extensions));
  const excludedCategories = new Set(normalizedValues(options.excludeCategories));
  const excludedSources = new Set(normalizedValues(options.excludeSourceModules));
  const extension = repositoryAssetExtension(asset);
  return asset.status === "ready"
    && (!categories.size || categories.has((asset.category || "").trim().toLowerCase()))
    && (!extensions.size || extensions.has(extension))
    && !excludedCategories.has((asset.category || "").trim().toLowerCase())
    && !excludedSources.has((asset.source_module || "").trim().toLowerCase());
}

/** The shared project-scoped read path for reusable repository files. */
export function useRepositoryAssets({
  projectId,
  categories,
  extensions,
  excludeCategories,
  excludeSourceModules,
  cacheKey = "repository-assets",
  enabled = true,
}: RepositoryAssetQueryOptions) {
  const normalizedCategories = useMemo(() => normalizedValues(categories), [categories]);
  const normalizedExtensions = useMemo(() => normalizedValues(extensions), [extensions]);
  const normalizedExcludedCategories = useMemo(() => normalizedValues(excludeCategories), [excludeCategories]);
  const normalizedExcludedSources = useMemo(() => normalizedValues(excludeSourceModules), [excludeSourceModules]);
  const query = useQuery({
    queryKey: [cacheKey, projectId, normalizedCategories, normalizedExtensions, normalizedExcludedCategories, normalizedExcludedSources],
    queryFn: () => uploadsApi.list({
      project_id: projectId || undefined,
      ...(normalizedCategories.length === 1 && !normalizedExtensions.length ? { category: normalizedCategories[0] } : {}),
      ...(normalizedExtensions.length === 1 && !normalizedCategories.length ? { extension: normalizedExtensions[0] } : {}),
    }).then((response) => response.data),
    enabled: Boolean(projectId) && enabled,
  });
  const assets = useMemo(() => (query.data || [])
    .filter((asset) => repositoryAssetMatches(asset, {
      categories: normalizedCategories,
      extensions: normalizedExtensions,
      excludeCategories: normalizedExcludedCategories,
      excludeSourceModules: normalizedExcludedSources,
    }))
    .sort((left, right) => right.created_at.localeCompare(left.created_at)),
  [normalizedCategories, normalizedExcludedCategories, normalizedExcludedSources, normalizedExtensions, query.data]);
  return { ...query, assets };
}
