export type Tier = 'novice' | 'advanced' | 'boss'
export type GameStatus = 'active' | 'paused' | 'completed'
export type LearningInputType = 'keyword' | 'url'
export type AcquisitionMethod = 'search' | 'extract'
export type GenerationMode = 'grounded' | 'legacy' | 'basic'
export type BattleRoomStatus = 'generating' | 'waiting' | 'playing' | 'finished' | 'void' | 'error'
export type BattleRole = 'host' | 'challenger'
export type BattleParticipantStatus = 'joined' | 'ready' | 'playing' | 'finished'
export type BattleOutcome = 'win' | 'lose' | 'draw'

export interface BasicGameRequest {
  topic: string
  fallback_token: string
  acknowledge_unverified: true
}

export interface BasicFallback {
  available: true
  token: string
  expires_at: string
  mode: 'basic'
  notice: '未经联网核验'
}

export interface AuthUser {
  id: string
  nickname: string
}

export interface LoginResponse {
  access_token: string
  token_type: 'bearer'
  user: AuthUser
}

export interface GameOption {
  index: number
  key: 'A' | 'B' | 'C'
  text: string
}

export interface BattleParticipant {
  role: BattleRole
  status: BattleParticipantStatus
  nickname: string
  correct_count: number | null
  total_seconds: number | null
  result: BattleOutcome | null
}

export interface BattleQuestion {
  position: number
  tier: Tier
  title: string
  intro: string
  question: string
  options: GameOption[]
}

export interface BattleRoom {
  id: string
  topic: string
  status: BattleRoomStatus
  error_message: string | null
  started_at: string | null
  expires_at: string | null
  me: BattleParticipant
  opponent: BattleParticipant | null
  question: BattleQuestion | null
}

export interface BattleAnswerResponse {
  result: 'correct' | 'wrong' | 'completed'
  question: BattleQuestion | null
}

export interface BattleReviewItem {
  position: number
  title: string
  question: string
  options: GameOption[]
  selected_option: number
  correct_option: number
  is_correct: boolean
  explanation: string
}

export interface BattleResult {
  room_id: string
  topic: string
  status: BattleRoomStatus
  my_result: BattleOutcome | null
  opponent_result: BattleOutcome | null
  my_correct_count: number
  opponent_correct_count: number | null
  my_total_seconds: number | null
  opponent_total_seconds: number | null
  review: BattleReviewItem[]
}

export interface GameLevel {
  position: number
  tier: Tier
  title: string
  intro: string
  question: string
  options: GameOption[]
}

export interface SourceReference {
  id: string
  title: string
  url: string
  domain: string
  acquisition_method: AcquisitionMethod
}

export interface Game {
  id: string
  topic: string
  title: string
  status: GameStatus
  hearts: number
  current_level: number
  progress: number
  level: GameLevel | null
  summary: string[]
  elapsed_seconds: number | null
  input_type: LearningInputType
  retrieved_at: string | null
  sources: SourceReference[]
  generation_mode?: GenerationMode
  verification_notice?: string | null
}

export type AnswerResult = 'correct' | 'wrong' | 'paused' | 'completed'

export interface AnswerResponse {
  result: AnswerResult
  message: string
  explanation: string | null
  game: Game
}

export interface ShareResponse {
  token: string
  path: string
  expires_at: string
}

export interface UserProfile {
  id: string
  nickname: string
  completed_games: number
  learned_points: number
  sound_enabled: boolean
  vibration_enabled: boolean
  web_search_enabled: boolean
}

export interface UserSettings {
  sound_enabled: boolean
  vibration_enabled: boolean
  web_search_enabled: boolean
}

export interface ApiErrorBody {
  error?: {
    code?: string
    message?: string
    details?: Record<string, unknown>
  }
}
