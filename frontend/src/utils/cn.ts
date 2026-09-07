import { clsx, type ClassValue } from 'clsx'

export function cn(...inputs: ClassValue[]) {
  return clsx(inputs)
}

export function formatStageLabel(label: string) {
  return label.replace(/^Stage:\s*/i, '')
}
