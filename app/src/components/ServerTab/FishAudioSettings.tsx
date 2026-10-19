import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
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
import { useToast } from '@/components/ui/use-toast';
import { apiClient } from '@/lib/api/client';
import type { FishModel, FishSettingsUpdate } from '@/lib/api/types';
import { SettingRow, SettingSection } from './SettingRow';

export function FishAudioSettings() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const [key, setKey] = useState('');
  const { data } = useQuery({
    queryKey: ['fishSettings'],
    queryFn: () => apiClient.getFishSettings(),
  });
  const update = useMutation({
    mutationFn: (patch: FishSettingsUpdate) => apiClient.updateFishSettings(patch),
    onSuccess: (settings) => {
      queryClient.setQueryData(['fishSettings'], settings);
      setKey('');
    },
    onError: (error: Error) =>
      toast({
        title: t('settings.fish.failed'),
        description: error.message,
        variant: 'destructive',
      }),
  });
  return (
    <SettingSection title="Fish Audio" description={t('settings.fish.description')}>
      <SettingRow
        title={t('settings.fish.key')}
        htmlFor="fishApiKey"
        description={t(data?.api_key_set ? 'settings.fish.configured' : 'settings.fish.missing')}
      >
        <div className="flex gap-2">
          <Input
            id="fishApiKey"
            type="password"
            autoComplete="off"
            value={key}
            onChange={(event) => setKey(event.target.value)}
          />
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={!key.trim() || update.isPending}
            onClick={() => update.mutate({ api_key: key.trim() })}
          >
            {t('settings.fish.save')}
          </Button>
          {data?.api_key_set && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={update.isPending}
              onClick={() => update.mutate({ api_key: '' })}
            >
              {t('settings.fish.clear')}
            </Button>
          )}
        </div>
      </SettingRow>
      <SettingRow
        title={t('settings.fish.model')}
        action={
          <Select
            value={data?.model ?? 's2.1-pro'}
            disabled={update.isPending}
            onValueChange={(model) => update.mutate({ model: model as FishModel })}
          >
            <SelectTrigger className="h-8 w-[180px] text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {(['s2.1-pro', 's2-pro', 's2.1-pro-free'] as const).map((model) => (
                <SelectItem key={model} value={model}>
                  {model}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        }
      />
    </SettingSection>
  );
}
