import { useMemo } from "react";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  FormControl,
  FormHelperText,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  Typography,
} from "@mui/material";
import FolderOutlinedIcon from "@mui/icons-material/FolderOutlined";
import { UploadedAsset } from "@/types/domain";
import {
  repositoryAssetBytes,
  repositoryAssetDate,
  useRepositoryAssets,
} from "@/components/repositoryAssets";
import type { RepositoryAssetQueryOptions } from "@/components/repositoryAssets";

export interface RepositoryAssetPickerProps extends RepositoryAssetQueryOptions {
  value: string;
  onChange: (assetId: string, asset: UploadedAsset | null) => void;
  assets?: UploadedAsset[];
  assetsLoading?: boolean;
  assetsError?: boolean;
  selectedAsset?: UploadedAsset | null;
  label?: string;
  emptyLabel?: string;
  noAssetsMessage?: string;
  helperText?: string;
  disabled?: boolean;
  onOpenRepository?: () => void;
}

/**
 * A compact single-file selector used by Autopilot and Test Execution. New
 * uploads remain the responsibility of the surrounding flow; this control
 * only selects an existing, project-owned repository asset by stable id.
 */
export default function RepositoryAssetPicker({
  projectId,
  categories,
  extensions,
  excludeCategories,
  excludeSourceModules,
  cacheKey,
  enabled = true,
  value,
  onChange,
  assets: providedAssets,
  assetsLoading,
  assetsError,
  selectedAsset: providedSelectedAsset,
  label = "Existing file in project repository",
  emptyLabel = "Upload a new file",
  noAssetsMessage = "No matching files are stored in this project yet. Upload a new file or open the repository.",
  helperText = "Select a reusable file already stored for this project.",
  disabled = false,
  onOpenRepository,
}: RepositoryAssetPickerProps) {
  const repositoryQuery = useRepositoryAssets({
    projectId,
    categories,
    extensions,
    excludeCategories,
    excludeSourceModules,
    cacheKey,
    enabled: providedAssets === undefined && enabled,
  });
  const assets = providedAssets ?? repositoryQuery.assets;
  const loading = providedAssets === undefined ? repositoryQuery.isLoading || repositoryQuery.isFetching : Boolean(assetsLoading);
  const hasError = providedAssets === undefined ? repositoryQuery.isError : Boolean(assetsError);
  const selectedAsset = providedSelectedAsset ?? assets.find((asset) => asset.id === value) ?? null;
  const options = useMemo(() => {
    if (!selectedAsset || assets.some((asset) => asset.id === selectedAsset.id)) return assets;
    return [selectedAsset, ...assets];
  }, [assets, selectedAsset]);
  const inputId = `repository-asset-${(cacheKey || "file").replace(/[^a-z0-9-]/gi, "-")}`;

  if (!projectId) return null;

  return (
    <Stack spacing={0.75}>
      <FormControl fullWidth size="small" disabled={disabled || loading} error={hasError}>
        <InputLabel id={`${inputId}-label`}>{label}</InputLabel>
        <Select
          labelId={`${inputId}-label`}
          label={label}
          value={value || ""}
          onChange={(event) => {
            const nextId = event.target.value;
            onChange(nextId, assets.find((asset) => asset.id === nextId) || null);
          }}
          renderValue={(selected) => {
            const asset = assets.find((item) => item.id === selected) || selectedAsset;
            return asset ? (
              <Box sx={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={asset.filename}>
                {asset.filename} · {repositoryAssetBytes(asset.size_bytes)}
              </Box>
            ) : <em>{emptyLabel}</em>;
          }}
        >
          <MenuItem value=""><em>{emptyLabel}</em></MenuItem>
          {options.map((asset) => (
            <MenuItem key={asset.id} value={asset.id} title={asset.filename}>
              <Box sx={{ display: "flex", alignItems: "center", gap: 1, minWidth: 0, width: "100%" }}>
                <Typography noWrap sx={{ minWidth: 0, flex: 1 }}>{asset.filename}</Typography>
                <Typography variant="caption" color="text.secondary" sx={{ whiteSpace: "nowrap" }}>
                  {repositoryAssetBytes(asset.size_bytes)} · {repositoryAssetDate(asset.created_at)}
                </Typography>
              </Box>
            </MenuItem>
          ))}
        </Select>
        {helperText && <FormHelperText>{helperText}</FormHelperText>}
      </FormControl>
      <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
        {loading && <Stack direction="row" spacing={0.75} alignItems="center"><CircularProgress size={14} /><Typography variant="caption" color="text.secondary">Checking project repository…</Typography></Stack>}
        {onOpenRepository && <Button size="small" startIcon={<FolderOutlinedIcon />} onClick={onOpenRepository} disabled={disabled}>Open repository</Button>}
      </Stack>
      {hasError && <Alert severity="warning">The project repository could not be loaded. You can retry this page or upload a new file.</Alert>}
      {!loading && !hasError && !options.length && <Typography variant="caption" color="text.secondary">{noAssetsMessage}</Typography>}
      {selectedAsset && <Typography variant="caption" color="text.secondary">Using repository asset · {selectedAsset.extension.toUpperCase()} · uploaded {repositoryAssetDate(selectedAsset.created_at)}</Typography>}
    </Stack>
  );
}
