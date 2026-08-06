import {
  closestCenter,
  DndContext,
  type DragEndEvent,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
} from '@dnd-kit/core';
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable';
import { useQuery } from '@tanstack/react-query';
import { Link } from '@tanstack/react-router';
import { AnimatePresence, motion } from 'framer-motion';
import { AudioWaveform, Download, Music, Plus, Upload } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import Loader from 'react-loaders';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { useToast } from '@/components/ui/use-toast';
import { apiClient } from '@/lib/api/client';
import { useHistory } from '@/lib/hooks/useHistory';
import {
  useAddStoryItem,
  useExportStoryAudio,
  useRemoveStoryItem,
  useReorderStoryItems,
  useStory,
} from '@/lib/hooks/useStories';
import { useStoryPlayback } from '@/lib/hooks/useStoryPlayback';
import { useStoryUndo } from '@/lib/hooks/useStoryUndo';
import { useGenerationStore } from '@/stores/generationStore';
import { useStoryStore } from '@/stores/storyStore';
import { SortableStoryChatItem } from './StoryChatItem';

export function StoryContent() {
  const { t } = useTranslation();
  const selectedStoryId = useStoryStore((state) => state.selectedStoryId);
  const { data: story, isLoading } = useStory(selectedStoryId);
  const removeItem = useRemoveStoryItem();
  const reorderItems = useReorderStoryItems();
  const exportAudio = useExportStoryAudio();
  const addStoryItem = useAddStoryItem();
  const { toast } = useToast();
  const scrollRef = useRef<HTMLDivElement>(null);
  const importInputRef = useRef<HTMLInputElement>(null);
  const pendingCount = useGenerationStore((s) => s.pendingGenerationIds.size);
  const addPendingGeneration = useGenerationStore((s) => s.addPendingGeneration);
  const addPendingStoryAdd = useGenerationStore((s) => s.addPendingStoryAdd);
  const pushUndo = useStoryUndo((s) => s.push);
  const [isDraggingFile, setIsDraggingFile] = useState(false);
  const [isImporting, setIsImporting] = useState(false);
  const [musicPrompt, setMusicPrompt] = useState('');
  const [isGeneratingMusic, setIsGeneratingMusic] = useState(false);
  const [freqPreset, setFreqPreset] = useState('');
  const [freqDuration, setFreqDuration] = useState('300');
  const [freqWithMusic, setFreqWithMusic] = useState(true);
  const [isGeneratingFreq, setIsGeneratingFreq] = useState(false);
  const { data: freqPresets } = useQuery({
    queryKey: ['frequencyPresets'],
    queryFn: () => apiClient.getFrequencyPresets(),
  });
  const dragDepthRef = useRef(0);

  // Add generation popover state
  const [searchQuery, setSearchQuery] = useState('');
  const [isAddOpen, setIsAddOpen] = useState(false);
  const { data: historyData } = useHistory();

  // Filter generations not in story and matching search
  const availableGenerations = useMemo(() => {
    if (!historyData?.items || !story) return [];
    const storyGenerationIds = new Set(story.items.map((i) => i.generation_id));
    const query = searchQuery.toLowerCase();
    return historyData.items.filter(
      (gen) =>
        gen.status === 'completed' &&
        !storyGenerationIds.has(gen.id) &&
        (gen.text.toLowerCase().includes(query) || gen.profile_name.toLowerCase().includes(query)),
    );
  }, [historyData, story, searchQuery]);

  // Get track editor height from store for dynamic padding
  const trackEditorHeight = useStoryStore((state) => state.trackEditorHeight);

  // Track editor is shown when story has items
  const hasBottomBar = story && story.items.length > 0;

  // Clear the floating generate box (always visible on this route) and the
  // track editor bar when it's showing.
  const FLOATING_BOX_CLEARANCE = 140;
  const bottomPadding = hasBottomBar
    ? trackEditorHeight + FLOATING_BOX_CLEARANCE
    : FLOATING_BOX_CLEARANCE;

  // Drag and drop sensors
  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: {
        distance: 8,
      },
    }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    }),
  );

  // Playback state (for auto-scroll and item highlighting)
  const isPlaying = useStoryStore((state) => state.isPlaying);
  const currentTimeMs = useStoryStore((state) => state.currentTimeMs);
  const playbackStoryId = useStoryStore((state) => state.playbackStoryId);

  // Refs for auto-scrolling to playing item
  const itemRefsMap = useRef<Map<string, HTMLDivElement>>(new Map());
  const lastScrolledItemRef = useRef<string | null>(null);

  // Use playback hook
  useStoryPlayback(story?.items);

  // Sort items by start_time_ms
  const sortedItems = useMemo(() => {
    if (!story?.items) return [];
    return [...story.items].sort((a, b) => a.start_time_ms - b.start_time_ms);
  }, [story?.items]);

  // Find the currently playing item based on timecode
  const currentlyPlayingItemId = useMemo(() => {
    if (!isPlaying || playbackStoryId !== story?.id || !sortedItems.length) {
      return null;
    }
    const playingItem = sortedItems.find((item) => {
      const itemStart = item.start_time_ms;
      const itemEnd = item.start_time_ms + item.duration * 1000;
      return currentTimeMs >= itemStart && currentTimeMs < itemEnd;
    });
    return playingItem?.generation_id ?? null;
  }, [isPlaying, playbackStoryId, story?.id, sortedItems, currentTimeMs]);

  // Auto-scroll to the currently playing item
  useEffect(() => {
    if (!currentlyPlayingItemId || currentlyPlayingItemId === lastScrolledItemRef.current) {
      return;
    }

    const element = itemRefsMap.current.get(currentlyPlayingItemId);
    if (element && scrollRef.current) {
      element.scrollIntoView({ behavior: 'smooth', block: 'start' });
      lastScrolledItemRef.current = currentlyPlayingItemId;
    }
  }, [currentlyPlayingItemId]);

  // Reset last scrolled item when playback stops
  useEffect(() => {
    if (!isPlaying) {
      lastScrolledItemRef.current = null;
    }
  }, [isPlaying]);

  const handleRegenerate = async (generationId: string) => {
    try {
      await apiClient.regenerateGeneration(generationId);
      addPendingGeneration(generationId);
    } catch (error) {
      toast({
        title: t('storyContent.toast.regenerateFailed'),
        description: error instanceof Error ? error.message : String(error),
        variant: 'destructive',
      });
    }
  };

  const handleRemoveItem = (itemId: string) => {
    if (!story) return;

    removeItem.mutate(
      {
        storyId: story.id,
        itemId,
      },
      {
        onError: (error) => {
          toast({
            title: t('storyContent.toast.removeFailed'),
            description: error.message,
            variant: 'destructive',
          });
        },
      },
    );
  };

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;

    if (!story || !over || active.id === over.id) return;

    const oldIndex = sortedItems.findIndex((item) => item.generation_id === active.id);
    const newIndex = sortedItems.findIndex((item) => item.generation_id === over.id);

    if (oldIndex === -1 || newIndex === -1) return;

    // Calculate the new order
    const newOrder = arrayMove(sortedItems, oldIndex, newIndex);
    const generationIds = newOrder.map((item) => item.generation_id);

    // Send reorder request to backend
    reorderItems.mutate(
      {
        storyId: story.id,
        data: { generation_ids: generationIds },
      },
      {
        onError: (error) => {
          toast({
            title: t('storyContent.toast.reorderFailed'),
            description: error.message,
            variant: 'destructive',
          });
        },
      },
    );
  };

  const handleExportAudio = () => {
    if (!story) return;

    exportAudio.mutate(
      {
        storyId: story.id,
        storyName: story.name,
      },
      {
        onError: (error) => {
          toast({
            title: t('storyContent.toast.exportFailed'),
            description: error.message,
            variant: 'destructive',
          });
        },
      },
    );
  };

  const handleImportAudio = async (file: File) => {
    if (!story) return;
    setIsImporting(true);
    try {
      const generation = await apiClient.importAudio(file);
      pushUndo(story.id, story.items);
      await addStoryItem.mutateAsync({
        storyId: story.id,
        data: { generation_id: generation.id },
      });
      setIsAddOpen(false);
    } catch (error) {
      toast({
        title: t('storyContent.toast.importFailed'),
        description: error instanceof Error ? error.message : String(error),
        variant: 'destructive',
      });
    } finally {
      setIsImporting(false);
    }
  };

  const handleImportFiles = async (files: FileList | File[]) => {
    for (const file of Array.from(files)) {
      await handleImportAudio(file);
    }
  };

  // Background layers (music, frequencies) go on their own track starting at
  // t=0 so they play UNDER the narration instead of being appended after it.
  const nextBackgroundTrack = () => {
    if (!story || story.items.length === 0) return 1;
    return Math.max(...story.items.map((i) => i.track)) + 1;
  };

  const handleGenerateMusic = async () => {
    if (!story || !musicPrompt.trim()) return;
    setIsGeneratingMusic(true);
    try {
      const generation = await apiClient.generateMusic({ prompt: musicPrompt.trim() });
      // Track for SSE progress; the story add fires when generation completes
      addPendingGeneration(generation.id);
      addPendingStoryAdd(generation.id, story.id, {
        startTimeMs: 0,
        track: nextBackgroundTrack(),
      });
      toast({ title: t('storyContent.musicQueued') });
      setMusicPrompt('');
      setIsAddOpen(false);
    } catch (error) {
      toast({
        title: t('storyContent.toast.musicFailed'),
        description: error instanceof Error ? error.message : String(error),
        variant: 'destructive',
      });
    } finally {
      setIsGeneratingMusic(false);
    }
  };

  const handleGenerateFrequency = async () => {
    if (!story || !freqPreset) return;
    setIsGeneratingFreq(true);
    try {
      // Rendered quiet so it sits under the voice as a bed by default.
      // with_music: MiniMax composes the ambient bed asynchronously and the
      // exact tone gets infused into it; pure mode is instant local synthesis.
      const generation = await apiClient.generateFrequency({
        preset: freqPreset,
        duration_sec: parseInt(freqDuration, 10),
        volume: 0.3,
        with_music: freqWithMusic,
      });
      if (generation.status === 'generating') {
        addPendingGeneration(generation.id);
        addPendingStoryAdd(generation.id, story.id, {
          startTimeMs: 0,
          track: nextBackgroundTrack(),
        });
        toast({ title: t('storyContent.musicQueued') });
      } else {
        pushUndo(story.id, story.items);
        await addStoryItem.mutateAsync({
          storyId: story.id,
          data: { generation_id: generation.id, start_time_ms: 0, track: nextBackgroundTrack() },
        });
      }
      setIsAddOpen(false);
    } catch (error) {
      toast({
        title: t('storyContent.toast.frequencyFailed'),
        description: error instanceof Error ? error.message : String(error),
        variant: 'destructive',
      });
    } finally {
      setIsGeneratingFreq(false);
    }
  };

  const handleAddGeneration = (generationId: string) => {
    if (!story) return;

    pushUndo(story.id, story.items);
    addStoryItem.mutate(
      {
        storyId: story.id,
        data: { generation_id: generationId },
      },
      {
        onSuccess: () => {
          setIsAddOpen(false);
          setSearchQuery('');
        },
        onError: (error) => {
          toast({
            title: t('storyContent.toast.addFailed'),
            description: error.message,
            variant: 'destructive',
          });
        },
      },
    );
  };

  if (!selectedStoryId) {
    return (
      <div className="flex items-center justify-center h-full text-muted-foreground">
        <div className="text-center">
          <p className="text-lg font-medium mb-2">{t('storyContent.selectStory.title')}</p>
          <p className="text-sm">{t('storyContent.selectStory.hint')}</p>
        </div>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-muted-foreground">{t('storyContent.loading')}</div>
      </div>
    );
  }

  if (!story) {
    return (
      <div className="flex items-center justify-center h-full text-muted-foreground">
        <div className="text-center">
          <p className="text-lg font-medium mb-2">{t('storyContent.notFound.title')}</p>
          <p className="text-sm">{t('storyContent.notFound.hint')}</p>
        </div>
      </div>
    );
  }

  return (
    <div
      className="flex flex-col h-full min-h-0 relative overflow-hidden"
      onDragEnter={(e) => {
        if (!e.dataTransfer?.types.includes('Files')) return;
        e.preventDefault();
        dragDepthRef.current += 1;
        setIsDraggingFile(true);
      }}
      onDragOver={(e) => {
        if (e.dataTransfer?.types.includes('Files')) e.preventDefault();
      }}
      onDragLeave={(e) => {
        if (!e.dataTransfer?.types.includes('Files')) return;
        dragDepthRef.current = Math.max(0, dragDepthRef.current - 1);
        if (dragDepthRef.current === 0) setIsDraggingFile(false);
      }}
      onDrop={(e) => {
        if (!e.dataTransfer?.files?.length) return;
        e.preventDefault();
        dragDepthRef.current = 0;
        setIsDraggingFile(false);
        handleImportFiles(e.dataTransfer.files);
      }}
    >
      <input
        ref={importInputRef}
        type="file"
        accept="audio/*,.wav,.mp3,.flac,.ogg,.m4a,.aac,.webm"
        multiple
        className="hidden"
        onChange={(e) => {
          if (e.target.files?.length) handleImportFiles(e.target.files);
          e.target.value = '';
        }}
      />
      {isDraggingFile && (
        <div className="absolute inset-0 z-30 pointer-events-none flex items-center justify-center bg-accent/10 border-2 border-dashed border-accent rounded-lg m-4">
          <div className="flex flex-col items-center gap-2 text-accent">
            <Music className="h-8 w-8" />
            <span className="text-sm font-medium">{t('storyContent.dropToImport')}</span>
          </div>
        </div>
      )}
      {/* Scroll Mask */}
      <div className="absolute top-0 left-0 right-0 h-20 bg-gradient-to-b from-background to-transparent z-10 pointer-events-none" />

      {/* Header */}
      <div className="absolute top-0 left-0 right-0 z-20 flex items-center justify-between px-1">
        <div>
          <h2 className="text-2xl font-bold">{story.name}</h2>
          {story.description && (
            <p className="text-sm text-muted-foreground mt-1">{story.description}</p>
          )}
        </div>
        <div className="flex gap-2 items-center">
          <AnimatePresence>
            {pendingCount > 0 && (
              <motion.div
                initial={{ opacity: 0, scale: 0.9, width: 0 }}
                animate={{ opacity: 1, scale: 1, width: 'auto' }}
                exit={{ opacity: 0, scale: 0.9, width: 0 }}
                transition={{ duration: 0.2 }}
              >
                <Link
                  to="/"
                  className="flex items-center gap-2 h-8 pl-1.5 pr-3 rounded-full bg-card border border-border hover:bg-muted/50 transition-all duration-200 cursor-pointer"
                >
                  <div className="shrink-0 w-10 h-5 overflow-hidden flex items-center justify-center">
                    <div className="scale-[0.45]">
                      <Loader type="line-scale" active />
                    </div>
                  </div>
                  <span className="text-xs text-muted-foreground whitespace-nowrap">
                    {t('storyContent.generatingCount', { count: pendingCount })}
                  </span>
                </Link>
              </motion.div>
            )}
          </AnimatePresence>
          <Popover open={isAddOpen} onOpenChange={setIsAddOpen}>
            <PopoverTrigger asChild>
              <Button variant="outline" size="sm">
                <Plus className="mr-2 h-4 w-4" />
                {t('storyContent.add')}
              </Button>
            </PopoverTrigger>
            <PopoverContent className="w-80 p-0" align="end">
              <div className="p-2 border-b space-y-2">
                <Input
                  placeholder={t('storyContent.searchPlaceholder')}
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  autoFocus
                />
                <Button
                  variant="outline"
                  size="sm"
                  className="w-full justify-start"
                  onClick={() => importInputRef.current?.click()}
                  disabled={isImporting}
                >
                  <Upload className="mr-2 h-4 w-4" />
                  {isImporting ? t('storyContent.importing') : t('storyContent.importAudio')}
                </Button>
                <div className="flex gap-2">
                  <Input
                    placeholder={t('storyContent.musicPromptPlaceholder')}
                    value={musicPrompt}
                    onChange={(e) => setMusicPrompt(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') handleGenerateMusic();
                    }}
                  />
                  <Button
                    variant="outline"
                    size="sm"
                    className="shrink-0 self-center"
                    onClick={handleGenerateMusic}
                    disabled={isGeneratingMusic || !musicPrompt.trim()}
                  >
                    <Music className="mr-2 h-4 w-4" />
                    {isGeneratingMusic
                      ? t('storyContent.musicGenerating')
                      : t('storyContent.generateMusic')}
                  </Button>
                </div>
                <div className="flex gap-2">
                  <Select value={freqPreset} onValueChange={setFreqPreset}>
                    <SelectTrigger className="flex-1 h-9 text-xs">
                      <SelectValue placeholder={t('storyContent.frequencyPlaceholder')} />
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
                      <SelectItem value="music" className="text-xs">
                        {t('storyContent.freqModeMusic')}
                      </SelectItem>
                      <SelectItem value="pure" className="text-xs">
                        {t('storyContent.freqModePure')}
                      </SelectItem>
                    </SelectContent>
                  </Select>
                  <Button
                    variant="outline"
                    size="sm"
                    className="shrink-0 self-center"
                    onClick={handleGenerateFrequency}
                    disabled={isGeneratingFreq || !freqPreset}
                    aria-label={t('storyContent.generateFrequency')}
                  >
                    <AudioWaveform className="h-4 w-4" />
                  </Button>
                </div>
              </div>
              <div className="max-h-60 overflow-y-auto">
                {availableGenerations.length === 0 ? (
                  <div className="p-4 text-center text-sm text-muted-foreground">
                    {searchQuery
                      ? t('storyContent.searchNoMatches')
                      : t('storyContent.searchNoAvailable')}
                  </div>
                ) : (
                  availableGenerations.map((gen) => (
                    <button
                      key={gen.id}
                      type="button"
                      className="w-full text-left px-3 py-2 hover:bg-muted transition-colors border-b last:border-b-0"
                      onClick={() => handleAddGeneration(gen.id)}
                    >
                      <div className="font-medium text-sm">{gen.profile_name}</div>
                      <div className="text-xs text-muted-foreground truncate">
                        {gen.text.length > 50 ? `${gen.text.substring(0, 50)}...` : gen.text}
                      </div>
                    </button>
                  ))
                )}
              </div>
            </PopoverContent>
          </Popover>
          {story.items.length > 0 && (
            <Button
              variant="outline"
              size="sm"
              onClick={handleExportAudio}
              disabled={exportAudio.isPending}
            >
              <Download className="mr-2 h-4 w-4" />
              {t('storyContent.exportAudio')}
            </Button>
          )}
        </div>
      </div>

      {/* Content */}
      <div
        ref={scrollRef}
        className="flex-1 min-h-0 overflow-y-auto space-y-3 pt-16 scroll-pt-16 relative z-0"
        style={{ paddingBottom: bottomPadding > 0 ? `${bottomPadding}px` : undefined }}
      >
        {sortedItems.length === 0 ? (
          <div className="text-center py-12 px-5 border-2 border-dashed border-muted rounded-md text-muted-foreground">
            <p className="text-sm">{t('storyContent.empty.title')}</p>
            <p className="text-xs mt-2">{t('storyContent.empty.hint')}</p>
          </div>
        ) : (
          <DndContext
            sensors={sensors}
            collisionDetection={closestCenter}
            onDragEnd={handleDragEnd}
          >
            <SortableContext
              items={sortedItems.map((item) => item.generation_id)}
              strategy={verticalListSortingStrategy}
            >
              <div className="space-y-3">
                {sortedItems.map((item, index) => (
                  <div
                    key={item.id}
                    ref={(el) => {
                      if (el) {
                        itemRefsMap.current.set(item.generation_id, el);
                      } else {
                        itemRefsMap.current.delete(item.generation_id);
                      }
                    }}
                  >
                    <SortableStoryChatItem
                      item={item}
                      storyId={story.id}
                      index={index}
                      onRemove={() => handleRemoveItem(item.id)}
                      onRegenerate={
                        item.engine === 'import'
                          ? undefined
                          : () => handleRegenerate(item.generation_id)
                      }
                      currentTimeMs={currentTimeMs}
                      isPlaying={isPlaying && playbackStoryId === story.id}
                    />
                  </div>
                ))}
              </div>
            </SortableContext>
          </DndContext>
        )}
      </div>
    </div>
  );
}
