import type { UseFormReturn } from 'react-hook-form';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import type { GenerationFormValues } from '@/lib/hooks/useGenerationForm';
import { locutionDirection, locutionSpeed, locutionText } from '@/lib/utils/locution';

export function LocutionTemplate({
  form,
  engine,
}: {
  form: UseFormReturn<GenerationFormValues>;
  engine: 'fish' | 'minimax';
}) {
  const { t } = useTranslation();
  return (
    <div className="mt-3 rounded-xl border border-border bg-card p-3 space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-sm font-medium">{t('generation.locution.title')}</span>
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={!!form.watch('text')?.trim()}
          onClick={() => {
            form.setValue('text', locutionText(engine), { shouldDirty: true });
            form.setValue('language', 'es');
            form.setValue('speed', locutionSpeed);
            form.setValue('pitch', 0);
            form.setValue('personality', false);
            form.setValue('instruct', engine === 'fish' ? locutionDirection : '');
          }}
        >
          {t('generation.locution.load')}
        </Button>
      </div>
      <p className="text-xs text-muted-foreground leading-relaxed">
        {t('generation.locution.hint')}
      </p>
      <p className="text-xs text-muted-foreground">{t('generation.locution.empty')}</p>
    </div>
  );
}
