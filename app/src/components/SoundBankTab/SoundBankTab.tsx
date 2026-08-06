import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  AudioWaveform,
  ListPlus,
  Loader2,
  Music,
  Play,
  Sparkles,
  Trash2,
  Wind,
} from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { useToast } from '@/components/ui/use-toast';
import { apiClient } from '@/lib/api/client';
import type { HistoryResponse } from '@/lib/api/types';
import { useHistory } from '@/lib/hooks/useHistory';
import { useStories } from '@/lib/hooks/useStories';
import { useGenerationStore } from '@/stores/generationStore';
import { usePlayerStore } from '@/stores/playerStore';

/** Profiles whose generations belong to the sound bank. */
const BANK_PROFILES = ['Meditation Music', 'Frequencies', 'Imported Audio'];

/** Curated sound recipes for meditation & manifestation.
 *  `hybrid_hz` recipes infuse an exact frequency into the AI soundscape. */
const SOUND_RECIPES: Array<{
  key: string;
  labelKey: string;
  prompt: string;
  hybrid_hz?: number;
}> = [
  {
    key: 'meditacion-profunda',
    labelKey: 'soundbank.recipes.deepMeditation',
    prompt:
      'deep meditation drone soundscape, warm continuous om tanpura drone, still, minimal, no melody, no percussion, timeless',
  },
  {
    key: 'manifestacion',
    labelKey: 'soundbank.recipes.manifestation',
    prompt:
      'manifestation meditation soundscape, warm ethereal sustained pads, soft shimmering textures, expansive, hopeful, no melody, no rhythm',
  },
  {
    key: 'handpan-1111',
    labelKey: 'soundbank.recipes.handpan1111',
    prompt:
      'hang drum handpan meditation, warm resonant handpan played very slowly, gentle melodic strikes with long ethereal sustain, spacious reverberant atmosphere, deeply relaxing, no drums, no other instruments',
    hybrid_hz: 1111,
  },
  {
    key: 'cuencos',
    labelKey: 'soundbank.recipes.bowls',
    prompt:
      'tibetan singing bowls meditation, sparse deep bowl strikes, long resonant decay, silence between strikes, monastery calm, no melody',
  },
  {
    key: 'chakras',
    labelKey: 'soundbank.recipes.chakras',
    prompt:
      'chakra healing soundscape, soft sustained singing tones slowly rising through seven pitches, gentle bowl resonances, spacious silence, no melody, no rhythm',
  },
  {
    key: 'limpieza-432',
    labelKey: 'soundbank.recipes.cleansing432',
    prompt:
      'negative energy cleansing soundscape, deep gong and bowl resonances, sparse purifying strikes, long silences, protective calm, no melody',
    hybrid_hz: 432,
  },
  {
    key: 'sueno',
    labelKey: 'soundbank.recipes.sleep',
    prompt:
      'deep sleep soundscape, very soft night ambience, slow fading dreamy textures, barely there, no melody, no rhythm',
  },
];

function formatDuration(seconds?: number): string {
  if (!seconds) return '—';
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}:${s.toString().padStart(2, '0')}`;
}

function BankItemRow({
  item,
  icon: Icon,
  onAddToStory,
}: {
  item: HistoryResponse;
  icon: typeof Music;
  onAddToStory: (generationId: string, storyId: string) => void;
}) {
  const { t } = useTranslation();
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const setAudioWithAutoPlay = usePlayerStore((s) => s.setAudioWithAutoPlay);
  const { data: stories } = useStories();

  const isGenerating = item.status === 'generating' || item.status === 'loading_model';
  const isFailed = item.status === 'failed';

  return (
    <div className="flex items-center gap-3 px-3 py-2 rounded-lg border border-border/60 bg-card/50 hover:bg-card transition-colors">
      <Icon className="h-4 w-4 shrink-0 text-accent" />
      <div className="flex-1 min-w-0">
        <p className="text-sm truncate">{item.text}</p>
        <p className="text-xs text-muted-foreground">
          {isGenerating
            ? t('soundbank.generating')
            : isFailed
              ? t('soundbank.failed')
              : formatDuration(item.duration)}
        </p>
      </div>
      {isGenerating ? (
        <Loader2 className="h-4 w-4 animate-spin text-muted-foreground shrink-0" />
      ) : (
        !isFailed && (
          <>
            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8 shrink-0"
              onClick={() =>
                setAudioWithAutoPlay(
                  apiClient.getAudioUrl(item.id),
                  item.id,
                  null,
                  item.text.slice(0, 60),
                )
              }
              title={t('soundbank.play')}
              aria-label={t('soundbank.play')}
            >
              <Play className="h-4 w-4" />
            </Button>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8 shrink-0"
                  title={t('soundbank.addToStory')}
                  aria-label={t('soundbank.addToStory')}
                >
                  <ListPlus className="h-4 w-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                {stories && stories.length > 0 ? (
                  stories.map((story) => (
                    <DropdownMenuItem
                      key={story.id}
                      onClick={() => onAddToStory(item.id, story.id)}
                      className="text-xs"
                    >
                      {story.name}
                    </DropdownMenuItem>
                  ))
                ) : (
                  <DropdownMenuItem disabled className="text-xs">
                    {t('soundbank.noStories')}
                  </DropdownMenuItem>
                )}
              </DropdownMenuContent>
            </DropdownMenu>
          </>
        )
      )}
      <Button
        variant="ghost"
        size="icon"
        className="h-8 w-8 shrink-0 text-muted-foreground hover:text-destructive"
        onClick={async () => {
          try {
            await apiClient.deleteGeneration(item.id);
            queryClient.invalidateQueries({ queryKey: ['history'] });
          } catch (error) {
            toast({
              title: t('soundbank.deleteFailed'),
              description: error instanceof Error ? error.message : String(error),
              variant: 'destructive',
            });
          }
        }}
        title={t('soundbank.delete')}
        aria-label={t('soundbank.delete')}
      >
        <Trash2 className="h-4 w-4" />
      </Button>
    </div>
  );
}

export function SoundBankTab() {
  const { t } = useTranslation();
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const addPendingGeneration = useGenerationStore((s) => s.addPendingGeneration);
  const { data: historyData } = useHistory({ limit: 100 });
  const { data: freqPresets } = useQuery({
    queryKey: ['frequencyPresets'],
    queryFn: () => apiClient.getFrequencyPresets(),
  });

  const [recipeKey, setRecipeKey] = useState('meditacion-profunda');
  const [customPrompt, setCustomPrompt] = useState('');
  const [isGeneratingSound, setIsGeneratingSound] = useState(false);
  const [freqPreset, setFreqPreset] = useState('');
  const [freqDuration, setFreqDuration] = useState('300');
  const [freqWithMusic, setFreqWithMusic] = useState(false);
  const [isGeneratingFreq, setIsGeneratingFreq] = useState(false);

  const bankItems = (historyData?.items ?? []).filter((i) =>
    BANK_PROFILES.includes(i.profile_name),
  );
  const sounds = bankItems.filter((i) => i.profile_name === 'Meditation Music');
  const frequencies = bankItems.filter((i) => i.profile_name === 'Frequencies');
  const imported = bankItems.filter((i) => i.profile_name === 'Imported Audio');

  const handleGenerateSound = async () => {
    const recipe = SOUND_RECIPES.find((r) => r.key === recipeKey);
    const prompt = customPrompt.trim() || recipe?.prompt;
    if (!prompt) return;
    setIsGeneratingSound(true);
    try {
      const generation = recipe?.hybrid_hz && !customPrompt.trim()
        ? await apiClient.generateFrequency({
            carrier_hz: recipe.hybrid_hz,
            mode: 'pure',
            duration_sec: 600,
            volume: 0.3,
            with_music: true,
            music_prompt: recipe.prompt,
          })
        : await apiClient.generateMusic({ prompt, instrumental: true });
      addPendingGeneration(generation.id);
      toast({ title: t('soundbank.queued') });
      setCustomPrompt('');
      queryClient.invalidateQueries({ queryKey: ['history'] });
    } catch (error) {
      toast({
        title: t('soundbank.generateFailed'),
        description: error instanceof Error ? error.message : String(error),
        variant: 'destructive',
      });
    } finally {
      setIsGeneratingSound(false);
    }
  };

  const handleGenerateFrequency = async () => {
    if (!freqPreset) return;
    setIsGeneratingFreq(true);
    try {
      const generation = await apiClient.generateFrequency({
        preset: freqPreset,
        duration_sec: parseInt(freqDuration, 10),
        volume: 0.4,
        with_music: freqWithMusic,
      });
      if (generation.status === 'generating') {
        addPendingGeneration(generation.id);
        toast({ title: t('soundbank.queued') });
      }
      queryClient.invalidateQueries({ queryKey: ['history'] });
    } catch (error) {
      toast({
        title: t('soundbank.generateFailed'),
        description: error instanceof Error ? error.message : String(error),
        variant: 'destructive',
      });
    } finally {
      setIsGeneratingFreq(false);
    }
  };

  const handleAddToStory = async (generationId: string, storyId: string) => {
    try {
      // Background layers land at t=0 on the next free track
      const story = await apiClient.getStory(storyId);
      const nextTrack =
        story.items.length > 0 ? Math.max(...story.items.map((i) => i.track)) + 1 : 1;
      await apiClient.addStoryItem(storyId, {
        generation_id: generationId,
        start_time_ms: 0,
        track: nextTrack,
      });
      queryClient.invalidateQueries({ queryKey: ['stories'] });
      toast({ title: t('soundbank.addedToStory') });
    } catch (error) {
      toast({
        title: t('soundbank.addFailed'),
        description: error instanceof Error ? error.message : String(error),
        variant: 'destructive',
      });
    }
  };

  return (
    <div className="flex flex-col h-full py-6 gap-5 overflow-hidden">
      <div className="shrink-0">
        <h1 className="text-lg font-semibold">{t('soundbank.title')}</h1>
        <p className="text-sm text-muted-foreground">{t('soundbank.subtitle')}</p>
      </div>

      {/* Generators */}
      <div className="shrink-0 grid gap-3 md:grid-cols-2">
        <div className="rounded-xl border p-3 space-y-2 bg-card/40">
          <p className="text-xs font-medium text-muted-foreground flex items-center gap-1.5">
            <Sparkles className="h-3.5 w-3.5" /> {t('soundbank.generateSound')}
          </p>
          <div className="flex gap-2">
            <Select value={recipeKey} onValueChange={setRecipeKey}>
              <SelectTrigger className="h-9 text-xs flex-1">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {SOUND_RECIPES.map((r) => (
                  <SelectItem key={r.key} value={r.key} className="text-xs">
                    {t(r.labelKey)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button
              size="sm"
              className="shrink-0"
              onClick={handleGenerateSound}
              disabled={isGeneratingSound}
            >
              {isGeneratingSound ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Music className="h-4 w-4" />
              )}
            </Button>
          </div>
          <Input
            value={customPrompt}
            onChange={(e) => setCustomPrompt(e.target.value)}
            placeholder={t('soundbank.customPromptPlaceholder')}
            className="h-8 text-xs"
          />
        </div>

        <div className="rounded-xl border p-3 space-y-2 bg-card/40">
          <p className="text-xs font-medium text-muted-foreground flex items-center gap-1.5">
            <AudioWaveform className="h-3.5 w-3.5" /> {t('soundbank.generateFrequency')}
          </p>
          <div className="flex gap-2">
            <Select value={freqPreset} onValueChange={setFreqPreset}>
              <SelectTrigger className="h-9 text-xs flex-1">
                <SelectValue placeholder={t('soundbank.frequencyPlaceholder')} />
              </SelectTrigger>
              <SelectContent>
                {freqPresets?.presets.map((p) => (
                  <SelectItem key={p.key} value={p.key} className="text-xs">
                    {p.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select value={freqDuration} onValueChange={setFreqDuration}>
              <SelectTrigger className="w-20 h-9 text-xs shrink-0">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="60" className="text-xs">1 min</SelectItem>
                <SelectItem value="300" className="text-xs">5 min</SelectItem>
                <SelectItem value="600" className="text-xs">10 min</SelectItem>
                <SelectItem value="1200" className="text-xs">20 min</SelectItem>
                <SelectItem value="1800" className="text-xs">30 min</SelectItem>
              </SelectContent>
            </Select>
            <Select
              value={freqWithMusic ? 'music' : 'pure'}
              onValueChange={(v) => setFreqWithMusic(v === 'music')}
            >
              <SelectTrigger className="w-24 h-9 text-xs shrink-0">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="pure" className="text-xs">
                  {t('soundbank.freqModePure')}
                </SelectItem>
                <SelectItem value="music" className="text-xs">
                  {t('soundbank.freqModeMusic')}
                </SelectItem>
              </SelectContent>
            </Select>
            <Button
              size="sm"
              className="shrink-0"
              onClick={handleGenerateFrequency}
              disabled={isGeneratingFreq || !freqPreset}
            >
              {isGeneratingFreq ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <AudioWaveform className="h-4 w-4" />
              )}
            </Button>
          </div>
        </div>
      </div>

      {/* Library */}
      <div className="flex-1 min-h-0 overflow-y-auto space-y-5 pb-6">
        <section>
          <h2 className="text-sm font-medium mb-2 flex items-center gap-1.5">
            <Music className="h-4 w-4 text-accent" /> {t('soundbank.sections.sounds')}
            <span className="text-xs text-muted-foreground">({sounds.length})</span>
          </h2>
          <div className="space-y-1.5">
            {sounds.length === 0 && (
              <p className="text-xs text-muted-foreground">{t('soundbank.empty')}</p>
            )}
            {sounds.map((item) => (
              <BankItemRow key={item.id} item={item} icon={Music} onAddToStory={handleAddToStory} />
            ))}
          </div>
        </section>

        <section>
          <h2 className="text-sm font-medium mb-2 flex items-center gap-1.5">
            <AudioWaveform className="h-4 w-4 text-accent" /> {t('soundbank.sections.frequencies')}
            <span className="text-xs text-muted-foreground">({frequencies.length})</span>
          </h2>
          <div className="space-y-1.5">
            {frequencies.length === 0 && (
              <p className="text-xs text-muted-foreground">{t('soundbank.empty')}</p>
            )}
            {frequencies.map((item) => (
              <BankItemRow
                key={item.id}
                item={item}
                icon={AudioWaveform}
                onAddToStory={handleAddToStory}
              />
            ))}
          </div>
        </section>

        {imported.length > 0 && (
          <section>
            <h2 className="text-sm font-medium mb-2 flex items-center gap-1.5">
              <Wind className="h-4 w-4 text-accent" /> {t('soundbank.sections.imported')}
              <span className="text-xs text-muted-foreground">({imported.length})</span>
            </h2>
            <div className="space-y-1.5">
              {imported.map((item) => (
                <BankItemRow
                  key={item.id}
                  item={item}
                  icon={Wind}
                  onAddToStory={handleAddToStory}
                />
              ))}
            </div>
          </section>
        )}
      </div>
    </div>
  );
}
