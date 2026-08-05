import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { FolderOpen, Languages, Mic, Zap } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Slider } from '@/components/ui/slider';
import { Toggle } from '@/components/ui/toggle';
import { useToast } from '@/components/ui/use-toast';
import { apiClient } from '@/lib/api/client';
import type { MiniMaxModel, MiniMaxSettingsUpdate } from '@/lib/api/types';
import { useGenerationSettings } from '@/lib/hooks/useSettings';
import { usePlatform } from '@/platform/PlatformContext';
import { useServerStore } from '@/stores/serverStore';
import { SettingRow, SettingSection } from './SettingRow';

const MINIMAX_MODELS: MiniMaxModel[] = [
  'speech-2.8-hd',
  'speech-2.8-turbo',
  'speech-2.6-hd',
  'speech-2.6-turbo',
  'speech-02-hd',
  'speech-02-turbo',
];

export function GenerationPage() {
  const { t } = useTranslation();
  const platform = usePlatform();
  const serverUrl = useServerStore((state) => state.serverUrl);
  const { settings, update } = useGenerationSettings();
  const persistedMaxChunkChars = settings?.max_chunk_chars ?? 800;
  const persistedCrossfadeMs = settings?.crossfade_ms ?? 50;
  const normalizeAudio = settings?.normalize_audio ?? true;
  const autoplayOnGenerate = settings?.autoplay_on_generate ?? true;
  // Slider mirrors persist on commit (pointer-up / keyboard-release) only —
  // onValueChange would fire a PATCH for every pointer-move pixel and round-
  // trip mid-drag failures could leave persisted state out of sync with UI.
  const [maxChunkChars, setMaxChunkChars] = useState(persistedMaxChunkChars);
  const [crossfadeMs, setCrossfadeMs] = useState(persistedCrossfadeMs);
  useEffect(() => setMaxChunkChars(persistedMaxChunkChars), [persistedMaxChunkChars]);
  useEffect(() => setCrossfadeMs(persistedCrossfadeMs), [persistedCrossfadeMs]);
  const [opening, setOpening] = useState(false);
  const [generationsPath, setGenerationsPath] = useState<string | null>(null);
  const { toast } = useToast();
  const queryClient = useQueryClient();

  const { data: minimaxSettings } = useQuery({
    queryKey: ['minimaxSettings'],
    queryFn: () => apiClient.getMiniMaxSettings(),
  });
  const [minimaxApiKey, setMinimaxApiKey] = useState('');
  const [minimaxGroupId, setMinimaxGroupId] = useState('');
  useEffect(() => setMinimaxGroupId(minimaxSettings?.group_id ?? ''), [minimaxSettings?.group_id]);
  const minimaxMutation = useMutation({
    mutationFn: (patch: MiniMaxSettingsUpdate) => apiClient.updateMiniMaxSettings(patch),
    onSuccess: (data) => {
      queryClient.setQueryData(['minimaxSettings'], data);
      setMinimaxApiKey('');
    },
    onError: (error: Error) => {
      toast({
        title: t('settings.minimax.saveFailed'),
        description: error.message,
        variant: 'destructive',
      });
    },
  });

  useEffect(() => {
    fetch(`${serverUrl}/health/filesystem`)
      .then((res) => res.json())
      .then((data) => {
        const genDir = data.directories?.find((d: { path: string }) =>
          d.path.includes('generations'),
        );
        if (genDir?.path) setGenerationsPath(genDir.path);
      })
      .catch(() => {});
  }, [serverUrl]);

  const openGenerationsFolder = useCallback(async () => {
    if (!generationsPath) return;
    setOpening(true);
    try {
      await platform.filesystem.openPath(generationsPath);
    } catch (e) {
      console.error('Failed to open generations folder:', e);
    } finally {
      setOpening(false);
    }
  }, [platform, generationsPath]);

  return (
    <div className="flex gap-8 items-start max-w-5xl">
      <div className="flex-1 min-w-0 max-w-2xl space-y-8">
      <SettingSection
        title={t('settings.generation.title')}
        description={t('settings.generation.description')}
      >
        <SettingRow
          title={t('settings.generation.chunkLimit.title')}
          description={t('settings.generation.chunkLimit.description')}
          action={
            <span className="text-sm tabular-nums text-muted-foreground">
              {t('settings.generation.chunkLimit.value', { chars: maxChunkChars })}
            </span>
          }
        >
          <Slider
            id="maxChunkChars"
            value={[maxChunkChars]}
            onValueChange={([value]) => setMaxChunkChars(value)}
            onValueCommit={([value]) => update({ max_chunk_chars: value })}
            min={100}
            max={5000}
            step={50}
            aria-label={t('settings.generation.chunkLimit.title')}
          />
        </SettingRow>

        <SettingRow
          title={t('settings.generation.crossfade.title')}
          description={t('settings.generation.crossfade.description')}
          action={
            <span className="text-sm tabular-nums text-muted-foreground">
              {crossfadeMs === 0
                ? t('settings.generation.crossfade.cut')
                : t('settings.generation.crossfade.ms', { ms: crossfadeMs })}
            </span>
          }
        >
          <Slider
            id="crossfadeMs"
            value={[crossfadeMs]}
            onValueChange={([value]) => setCrossfadeMs(value)}
            onValueCommit={([value]) => update({ crossfade_ms: value })}
            min={0}
            max={200}
            step={10}
            aria-label={t('settings.generation.crossfade.title')}
          />
        </SettingRow>

        <SettingRow
          title={t('settings.generation.normalize.title')}
          description={t('settings.generation.normalize.description')}
          htmlFor="normalizeAudio"
          action={
            <Toggle
              id="normalizeAudio"
              checked={normalizeAudio}
              onCheckedChange={(v) => update({ normalize_audio: v })}
            />
          }
        />

        <SettingRow
          title={t('settings.generation.autoplay.title')}
          description={t('settings.generation.autoplay.description')}
          htmlFor="autoplayOnGenerate"
          action={
            <Toggle
              id="autoplayOnGenerate"
              checked={autoplayOnGenerate}
              onCheckedChange={(v) => update({ autoplay_on_generate: v })}
            />
          }
        />

        <SettingRow
          title={t('settings.generation.folder.title')}
          description={generationsPath ?? t('settings.generation.folder.description')}
          action={
            <Button
              variant="outline"
              size="sm"
              onClick={openGenerationsFolder}
              disabled={opening || !generationsPath}
            >
              <FolderOpen className="h-3.5 w-3.5 mr-1.5" />
              {t('settings.generation.folder.open')}
            </Button>
          }
        />
      </SettingSection>

      <SettingSection
        title={t('settings.minimax.title')}
        description={t('settings.minimax.description')}
      >
        <SettingRow
          title={t('settings.minimax.apiKey.title')}
          description={
            minimaxSettings?.api_key_set
              ? t('settings.minimax.apiKey.configured', {
                  preview: minimaxSettings.api_key_preview,
                })
              : t('settings.minimax.apiKey.notConfigured')
          }
          htmlFor="minimaxApiKey"
        >
          <div className="flex gap-2">
            <Input
              id="minimaxApiKey"
              type="password"
              value={minimaxApiKey}
              onChange={(e) => setMinimaxApiKey(e.target.value)}
              placeholder={t('settings.minimax.apiKey.placeholder')}
              autoComplete="off"
            />
            <Button
              variant="outline"
              size="sm"
              className="shrink-0 self-center"
              disabled={!minimaxApiKey.trim() || minimaxMutation.isPending}
              onClick={() => minimaxMutation.mutate({ api_key: minimaxApiKey.trim() })}
            >
              {t('settings.minimax.apiKey.save')}
            </Button>
            {minimaxSettings?.api_key_set && (
              <Button
                variant="ghost"
                size="sm"
                className="shrink-0 self-center text-muted-foreground"
                disabled={minimaxMutation.isPending}
                onClick={() => minimaxMutation.mutate({ api_key: '' })}
              >
                {t('settings.minimax.apiKey.clear')}
              </Button>
            )}
          </div>
        </SettingRow>

        <SettingRow
          title={t('settings.minimax.model.title')}
          description={t('settings.minimax.model.description')}
          action={
            <Select
              value={minimaxSettings?.model ?? 'speech-2.8-hd'}
              onValueChange={(v) => minimaxMutation.mutate({ model: v as MiniMaxModel })}
            >
              <SelectTrigger className="h-8 w-[180px] text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {MINIMAX_MODELS.map((model) => (
                  <SelectItem key={model} value={model} className="text-xs">
                    {model}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          }
        />

        <SettingRow
          title={t('settings.minimax.groupId.title')}
          description={t('settings.minimax.groupId.description')}
          htmlFor="minimaxGroupId"
        >
          <Input
            id="minimaxGroupId"
            value={minimaxGroupId}
            onChange={(e) => setMinimaxGroupId(e.target.value)}
            onBlur={() => {
              if ((minimaxSettings?.group_id ?? '') !== minimaxGroupId) {
                minimaxMutation.mutate({ group_id: minimaxGroupId });
              }
            }}
            placeholder={t('settings.minimax.groupId.placeholder')}
            autoComplete="off"
          />
        </SettingRow>
      </SettingSection>
      </div>

      <aside className="hidden lg:block w-[280px] shrink-0 space-y-6 sticky top-0">
        <div className="space-y-2">
          <h3 className="text-sm font-semibold">{t('settings.generation.sidebar.aboutTitle')}</h3>
          <p className="text-sm text-muted-foreground leading-relaxed">
            {t('settings.generation.sidebar.aboutBody')}
          </p>
        </div>

        <div className="space-y-3">
          <h3 className="text-sm font-semibold">{t('settings.generation.sidebar.differencesTitle')}</h3>
          <ul className="space-y-3 text-sm text-muted-foreground">
            <li className="flex gap-2.5">
              <Mic className="h-4 w-4 shrink-0 mt-0.5 text-accent" />
              <span className="leading-relaxed">
                <span className="text-foreground font-medium">
                  {t('settings.generation.sidebar.clone.title')}
                </span>{' '}
                {t('settings.generation.sidebar.clone.body')}
              </span>
            </li>
            <li className="flex gap-2.5">
              <Languages className="h-4 w-4 shrink-0 mt-0.5 text-accent" />
              <span className="leading-relaxed">
                <span className="text-foreground font-medium">
                  {t('settings.generation.sidebar.engines.title')}
                </span>{' '}
                {t('settings.generation.sidebar.engines.body')}
              </span>
            </li>
            <li className="flex gap-2.5">
              <Zap className="h-4 w-4 shrink-0 mt-0.5 text-accent" />
              <span className="leading-relaxed">
                <span className="text-foreground font-medium">{t('settings.generation.sidebar.agentReady.title')}</span>{' '}
                {t('settings.generation.sidebar.agentReady.body')}
              </span>
            </li>
          </ul>
        </div>
      </aside>
    </div>
  );
}
