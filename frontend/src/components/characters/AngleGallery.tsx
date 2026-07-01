import type { CharacterDetail } from "@/lib/types"
import { fileUrl } from "@/lib/api"

type Props = {
  character: CharacterDetail
}

const ANGLE_LABELS: Record<string, string> = {
  front: "전면",
  back: "후면",
  side: "측면",
  three_quarter: "3/4",
}

const ANGLE_FIELDS: { angle: string; field: keyof CharacterDetail }[] = [
  { angle: "front", field: "angle_front_path" },
  { angle: "back", field: "angle_back_path" },
  { angle: "side", field: "angle_side_path" },
  { angle: "three_quarter", field: "angle_three_quarter_path" },
]

export function AngleGallery({ character }: Props) {
  return (
    <div className="grid grid-cols-2 gap-3" role="group" aria-label="캐릭터 각도 갤러리">
      {ANGLE_FIELDS.map(({ angle, field }) => {
        const path = character[field] as string | null
        return (
          <div
            key={angle}
            className="overflow-hidden rounded-lg border border-border bg-card"
            role="img"
            aria-label={`${ANGLE_LABELS[angle]} 각도${path ? "" : " — 이미지 없음"}`}
          >
            {path ? (
              <img
                src={fileUrl(path)}
                alt={`${character.canonical_name} ${ANGLE_LABELS[angle]}`}
                className="aspect-square w-full object-cover"
                loading="lazy"
              />
            ) : (
              <div className="flex aspect-square items-center justify-center text-[12px] text-muted-foreground">
                <span className="text-center">
                  <span className="block text-[20px] mb-1 opacity-40">🖼</span>
                  {ANGLE_LABELS[angle]}<br />이미지 없음
                </span>
              </div>
            )}
            <div className="px-3 py-1.5 border-t border-border">
              <span className="text-[11px] font-medium text-muted-foreground">{ANGLE_LABELS[angle]}</span>
            </div>
          </div>
        )
      })}
    </div>
  )
}
