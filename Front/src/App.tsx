import { useEffect, useMemo, useRef, useState } from "react"
import {
  Activity,
  AlertCircle,
  AlertTriangle,
  ArrowLeft,
  Check,
  ChevronDown,
  ChevronRight,
  Circle,
  Clock3,
  FileSearch,
  FileText,
  Home,
  Info,
  ListChecks,
  Loader2,
  Pencil,
  Play,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  TrendingUp,
  X,
} from "lucide-react"
import {
  Area,
  AreaChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip as ChartTooltip,
  XAxis,
  YAxis,
} from "recharts"
import {
  APP_CONFIG,
  INDUSTRIES,
  PREFERENCES,
  QUESTIONS,
  SECURITIES,
  TENDENCIES,
} from "./config"
import { DEMO_PROFILE, makeDemoReport } from "./fixtures"
import {
  calculateMetrics,
  defaultConditions,
  format,
  validateProfile,
} from "./lib"
import { localDataService } from "./localDataService"
import type {
  AnalysisDraft,
  AppData,
  DemoOutcome,
  EffectiveConditions,
  Evidence,
  ExecutionRecord,
  PaperPortfolio,
  Profile,
  Report,
  StageStatus,
  Tendency,
} from "./types"

type Route = { page: "home" } | { page: "profile" mode?: "setup" | "edit" } | {
  page: "review"
} | { page: "run" } | { page: "reports" } | { page: "report" id: string } | {
  page: "paper"
} | { page: "paper-detail" id: string } | { page: "comparison" id: string }

const EMPTY_PROFILE: Profile = {
  ...DEMO_PROFILE,
  amountKrw: 0,
  industries: [],
  preferences: [],
  memo: "",
  excludedTickers: [],
  securityCaps: {},
  allowEtf: false,
}

const routePath = (route: Route) => {
  if (route.page === "home") return "#/home"
  if (route.page === "profile")
    return route.mode === "setup" ? "#/profile/setup" : "#/profile"
  if (route.page === "review") return "#/analysis/review"
  if (route.page === "run") return "#/analysis/run"
  if (route.page === "reports") return "#/reports"
  if (route.page === "report") return `#/reports/${route.id}`
  if (route.page === "paper") return "#/paper"
  if (route.page === "paper-detail") return `#/paper/${route.id}`
  return `#/comparison/${route.id}`
}

const parseRoute = (): Route => {
  const path = window.location.hash.replace(/^#/, "") || "/home"
  const parts = path.split("/").filter(Boolean)
  if (parts[0] === "profile")
    return { page: "profile", mode: parts[1] === "setup" ? "setup" : undefined }
  if (parts[0] === "analysis" && parts[1] === "review")
    return { page: "review" }
  if (parts[0] === "analysis" && parts[1] === "run") return { page: "run" }
  if (parts[0] === "reports" && parts[1])
    return { page: "report", id: parts[1] }
  if (parts[0] === "reports") return { page: "reports" }
  if (parts[0] === "paper" && parts[1])
    return { page: "paper-detail", id: parts[1] }
  if (parts[0] === "paper") return { page: "paper" }
  if (parts[0] === "comparison" && parts[1])
    return { page: "comparison", id: parts[1] }
  return { page: "home" }
}

function Button({
  children,
  variant = "primary",
  className = "",
  disabled,
  onClick,
  type = "button",
}: {
  children: React.ReactNode
  variant?: "primary" | "secondary" | "ghost" | "danger"
  className?: string
  disabled?: boolean
  onClick?: () => void
  type?: "button" | "submit"
}) {
  const variants = {
    primary: "bg-blue-700 text-white border-blue-700 hover:bg-blue-800",
    secondary: "bg-white text-blue-700 border-blue-200 hover:bg-blue-50",
    ghost:
      "bg-transparent text-slate-600 border-transparent hover:bg-slate-100",
    danger: "bg-white text-red-700 border-red-200 hover:bg-red-50",
  }
  return (
    <button
      type={type}
      disabled={disabled}
      onClick={onClick}
      className={`inline-flex min-h-10 items-center justify-center gap-2 rounded-xl border px-4 py-2 text-sm font-semibold transition focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 ${variants[variant]} ${className}`}
    >
      {children}
    </button>
  )
}

function IconButton({
  label,
  onClick,
  children,
}: {
  label: string
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      aria-label={label}
      onClick={onClick}
      className="rounded-lg p-2 text-slate-500 transition hover:bg-slate-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
    >
      {children}
    </button>
  )
}

function Card({
  children,
  className = "",
}: {
  children: React.ReactNode
  className?: string
}) {
  return (
    <section
      className={`rounded-2xl border border-slate-200 bg-white ${className}`}
    >
      {children}
    </section>
  )
}

function Badge({
  children,
  tone = "blue",
}: {
  children: React.ReactNode
  tone?: "blue" | "green" | "amber" | "red" | "slate"
}) {
  const tones = {
    blue: "border-blue-200 bg-blue-50 text-blue-700",
    green: "border-emerald-200 bg-emerald-50 text-emerald-700",
    amber: "border-amber-200 bg-amber-50 text-amber-800",
    red: "border-red-200 bg-red-50 text-red-700",
    slate: "border-slate-200 bg-slate-50 text-slate-600",
  }
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs font-semibold ${tones[tone]}`}
    >
      {children}
    </span>
  )
}

function Alert({
  title,
  children,
  tone = "info",
}: {
  title: string
  children: React.ReactNode
  tone?: "info" | "warning" | "error" | "success"
}) {
  const tones = {
    info: "border-blue-200 bg-blue-50 text-blue-950",
    warning: "border-amber-200 bg-amber-50 text-amber-950",
    error: "border-red-200 bg-red-50 text-red-950",
    success: "border-emerald-200 bg-emerald-50 text-emerald-950",
  }
  const Icon =
    tone === "error"
      ? AlertCircle
      : tone === "success"
        ? ShieldCheck
        : tone === "warning"
          ? AlertTriangle
          : Info
  return (
    <div
      className={`flex gap-3 rounded-xl border p-4 ${tones[tone]}`}
      role={tone === "error" ? "alert" : "status"}
    >
      <Icon className="mt-0.5 size-5 shrink-0" />
      <div>
        <p className="text-sm font-semibold">{title}</p>
        <div className="mt-1 text-sm leading-6 opacity-80">{children}</div>
      </div>
    </div>
  )
}

function Field({
  label,
  error,
  help,
  children,
}: {
  label: string
  error?: string
  help?: string
  children: React.ReactNode
}) {
  return (
    <label className="block">
      <span className="mb-2 block text-sm font-semibold text-slate-700">
        {label}
      </span>
      {children}
      {help && !error && (
        <span className="mt-1.5 block text-xs leading-5 text-slate-500">
          {help}
        </span>
      )}
      {error && (
        <span className="mt-1.5 block text-xs font-medium text-red-600">
          {error}
        </span>
      )}
    </label>
  )
}

const inputClass =
  "w-full rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-blue-400 focus:ring-2 focus:ring-blue-100"

function PageHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow?: string
  title: string
  description?: string
  actions?: React.ReactNode
}) {
  return (
    <header className="flex items-start justify-between gap-8">
      <div className="max-w-3xl">
        {eyebrow && (
          <p className="mb-2 text-xs font-bold tracking-widest text-blue-700">
            {eyebrow}
          </p>
        )}
        <h1 className="text-3xl font-bold tracking-tight text-slate-950">
          {title}
        </h1>
        {description && (
          <p className="mt-2 text-sm leading-6 text-slate-600">{description}</p>
        )}
      </div>
      {actions && <div className="flex shrink-0 gap-2">{actions}</div>}
    </header>
  )
}

function EmptyState({
  title,
  description,
  action,
}: {
  title: string
  description: string
  action?: React.ReactNode
}) {
  return (
    <Card className="flex min-h-72 flex-col items-center justify-center p-8 text-center">
      <FileSearch className="size-10 text-slate-300" />
      <h2 className="mt-4 text-lg font-bold text-slate-900">{title}</h2>
      <p className="mt-2 max-w-md text-sm leading-6 text-slate-500">
        {description}
      </p>
      {action && <div className="mt-5">{action}</div>}
    </Card>
  )
}

function Sidebar({
  route,
  reports,
  paperCount,
  navigate,
}: {
  route: Route
  reports: Report[]
  paperCount: number
  navigate: (route: Route) => void
}) {
  const items = [
    {
      label: "홈 · 새 분석",
      icon: Home,
      route: { page: "home" } as Route,
      active: ["home", "review", "run"].includes(route.page),
    },
    {
      label: "분석 리포트",
      icon: FileText,
      route: { page: "reports" } as Route,
      active: ["reports", "report", "comparison"].includes(route.page),
    },
    {
      label: "모의투자",
      icon: Activity,
      route: { page: "paper" } as Route,
      active: ["paper", "paper-detail"].includes(route.page),
      count: paperCount,
    },
    {
      label: "내 투자조건",
      icon: SlidersHorizontal,
      route: { page: "profile" } as Route,
      active: route.page === "profile",
    },
  ]
  return (
    <aside className="sticky top-0 flex h-screen w-60 shrink-0 flex-col border-r border-slate-200 bg-white px-4 py-6">
      <button
        onClick={() => navigate({ page: "home" })}
        className="flex items-center gap-3 rounded-xl px-2 text-left focus:outline-none focus:ring-2 focus:ring-blue-500"
      >
        <span className="flex size-9 items-center justify-center rounded-xl bg-blue-700 text-white">
          <TrendingUp className="size-5" />
        </span>
        <span>
          <span className="block text-base font-extrabold tracking-tight text-slate-950">
            MyFinSight
          </span>
          <span className="block text-[10px] font-medium text-slate-400">
            개인화 투자전략
          </span>
        </span>
      </button>
      <nav className="mt-8 space-y-1" aria-label="주 메뉴">
        {items.map((item) => (
          <button
            key={item.label}
            onClick={() => navigate(item.route)}
            className={`flex w-full items-center justify-between rounded-xl px-3 py-2.5 text-sm font-semibold transition focus:outline-none focus:ring-2 focus:ring-blue-500 ${
              item.active
                ? "bg-blue-50 text-blue-700"
                : "text-slate-600 hover:bg-slate-50 hover:text-slate-900"
            }`}
          >
            <span className="flex items-center gap-3">
              <item.icon className="size-4" />
              {item.label}
            </span>
            {item.count !== undefined && (
              <span className="rounded-full bg-blue-700 px-2 py-0.5 text-[10px] text-white">
                {item.count}
              </span>
            )}
          </button>
        ))}
      </nav>
      <div className="mt-5 border-t border-slate-100 pt-5">
        <p className="px-3 text-[11px] font-bold tracking-wider text-slate-400">
          최근 리포트
        </p>
        <div className="mt-2 space-y-1">
          {reports.slice(0, 5).map((report) => (
            <button
              key={report.id}
              onClick={() => navigate({ page: "report", id: report.id })}
              className={`w-full rounded-lg px-3 py-2 text-left transition hover:bg-slate-50 focus:outline-none focus:ring-2 focus:ring-blue-500 ${
                route.page === "report" && route.id === report.id
                  ? "bg-blue-50"
                  : ""
              }`}
            >
              <span className="block truncate text-xs font-semibold text-slate-700">
                {report.title}
              </span>
              <span className="mt-0.5 block text-[10px] text-slate-400">
                {report.createdAt}
              </span>
            </button>
          ))}
        </div>
      </div>
    </aside>
  )
}

function Shell({
  route,
  data,
  navigate,
  children,
}: {
  route: Route
  data: AppData
  navigate: (route: Route) => void
  children: React.ReactNode
}) {
  return (
    <div className="flex min-h-screen min-w-[1180px] bg-slate-50">
      <Sidebar
        route={route}
        reports={data.reports}
        paperCount={data.paperPortfolios.length}
        navigate={navigate}
      />
      <main className="min-w-0 flex-1 overflow-x-auto">
        <div className="mx-auto w-full max-w-[1180px] px-10 py-9">
          {children}
        </div>
      </main>
    </div>
  )
}

function ProfileWizard({
  initial,
  setup,
  onSave,
  onCancel,
}: {
  initial: Profile
  setup: boolean
  onSave: (profile: Profile, simulateFailure: boolean) => Promise<boolean>
  onCancel: () => void
}) {
  const [step, setStep] = useState(1)
  const [profile, setProfile] = useState(structuredClone(initial))
  const [amountText, setAmountText] = useState(
    initial.amountKrw.toLocaleString("ko-KR"),
  )
  const [duration, setDuration] = useState(
    initial.horizonMonths % 12 === 0
      ? initial.horizonMonths / 12
      : initial.horizonMonths,
  )
  const [unit, setUnit] = useState<"년" | "개월">(
    initial.horizonMonths % 12 === 0 ? "년" : "개월",
  )
  const [answers, setAnswers] = useState<Record<string, number>>({})
  const [loss, setLoss] = useState(initial.lossTolerancePct)
  const [overrideConfirmed, setOverrideConfirmed] = useState(
    !initial.tendencyOverridden,
  )
  const [advanced, setAdvanced] = useState(false)
  const [securitySearch, setSecuritySearch] = useState("")
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState("")

  const score = Object.values(answers).reduce((sum, value) => sum + value, 0)
  const computed = TENDENCIES[Math.min(4, Math.floor(score / 2.3))]

  useEffect(() => {
    setProfile((current) => ({
      ...current,
      computedTendency: computed,
      lossTolerancePct: loss,
    }))
  }, [computed, loss])

  const next = () => {
    const horizonMonths = unit === "년" ? duration * 12 : duration
    const candidate = {
      ...profile,
      amountKrw: Number(amountText.replaceAll(",", "")),
      horizonMonths,
    }
    const found = validateProfile(candidate)
    if (step === 1 && (found.amountKrw || found.horizonMonths)) {
      setErrors(found)
      return
    }
    if (step === 2 && Object.keys(answers).length < QUESTIONS.length) {
      setErrors({
        questionnaire: "필수 질문에 모두 답해주세요.",
      })
      return
    }
    if (
      step === 2 &&
      profile.finalTendency !== computed &&
      !overrideConfirmed
    ) {
      setErrors({
        tendency: "계산 결과와 다른 성향을 선택하려면 차이를 확인해주세요.",
      })
      return
    }
    setProfile(candidate)
    setErrors({})
    setStep((value) => Math.min(3, value + 1))
  }

  const submit = async () => {
    const candidate = {
      ...profile,
      amountKrw: Number(amountText.replaceAll(",", "")),
      horizonMonths: unit === "년" ? duration * 12 : duration,
      tendencyOverridden: profile.finalTendency !== computed,
      computedTendency: computed,
    }
    const found = validateProfile(candidate)
    if (Object.keys(found).length) {
      setErrors(found)
      setAdvanced(true)
      return
    }
    setSaving(true)
    setSaveError("")
    const ok = await onSave(candidate, false)
    setSaving(false)
    if (!ok)
      setSaveError("투자조건을 저장하지 못했습니다. 입력값은 유지됩니다.")
  }

  const filtered = SECURITIES.filter(
    (security) =>
      security.ticker.toLowerCase().includes(securitySearch.toLowerCase()) ||
      security.name.toLowerCase().includes(securitySearch.toLowerCase()),
  ).slice(0, 5)

  return (
    <div className="mx-auto max-w-4xl">
      <PageHeader
        eyebrow={setup ? "처음 설정" : "투자조건 수정"}
        title={
          setup
            ? "기본 투자조건을 알려주세요."
            : "저장된 투자조건을 수정합니다."
        }
        description="금액과 투자기간, 투자성향, 관심 분야를 차례로 설정합니다."
      />
      <div className="my-8 grid grid-cols-3 gap-3">
        {["기본 조건", "투자성향", "관심·제약"].map((label, index) => (
          <div
            key={label}
            className={`rounded-xl border p-3 ${
              step === index + 1
                ? "border-blue-300 bg-blue-50"
                : "border-slate-200 bg-white"
            }`}
          >
            <p className="text-xs font-bold text-slate-400">0{index + 1}</p>
            <p className="mt-1 text-sm font-semibold text-slate-800">{label}</p>
          </div>
        ))}
      </div>

      <Card className="p-7">
        {step === 1 && (
          <div className="space-y-6">
            <div>
              <h2 className="text-lg font-bold text-slate-950">
                기본 투자조건
              </h2>
              <p className="mt-1 text-sm text-slate-500">
                입력한 금액과 기간은 분석의 계산 조건으로 사용됩니다.
              </p>
            </div>
            <Field label="투자 금액" error={errors.amountKrw}>
              <div className="relative">
                <input
                  className={`${inputClass} pr-10`}
                  inputMode="numeric"
                  value={amountText}
                  onChange={(event) => {
                    const value = event.target.value.replace(/\D/g, "")
                    setAmountText(
                      value ? Number(value).toLocaleString("ko-KR") : "",
                    )
                  }}
                />
                <span className="absolute right-3 top-2.5 text-sm text-slate-500">
                  원
                </span>
              </div>
            </Field>
            <Field
              label="투자기간"
              error={errors.horizonMonths}
              help={`입력 가능한 투자기간은 ${APP_CONFIG.horizon.minMonths}~${APP_CONFIG.horizon.maxMonths}개월입니다.`}
            >
              <div className="grid grid-cols-[1fr_140px] gap-3">
                <input
                  className={inputClass}
                  type="number"
                  min={1}
                  value={duration}
                  onChange={(event) => setDuration(Number(event.target.value))}
                />
                <select
                  className={inputClass}
                  value={unit}
                  onChange={(event) =>
                    setUnit(event.target.value as "년" | "개월")
                  }
                >
                  <option>년</option>
                  <option>개월</option>
                </select>
              </div>
            </Field>
            <Alert title="지원 시장: 미국" tone="info">
              시장은 선택 항목이 아닙니다. 현재 미국 시장만 지원합니다. S&P
              500과 Nasdaq-100은 투자 대상 범위 또는 비교지수로만 사용됩니다.
            </Alert>
          </div>
        )}

        {step === 2 && (
          <div className="space-y-6">
            <div>
              <h2 className="text-lg font-bold text-slate-950">
                투자성향 평가
              </h2>
              <p className="mt-1 text-sm text-slate-500">
                투자 경험과 손실에 대한 생각을 확인합니다. 금융회사의 적합성
                평가를 대신하지 않습니다.
              </p>
            </div>
            {QUESTIONS.map((question) => (
              <fieldset key={question.id}>
                <legend className="text-sm font-semibold text-slate-800">
                  {question.question}
                  {question.id === "loss" && " (필수)"}
                </legend>
                <div className="mt-2 grid grid-cols-2 gap-2">
                  {question.options.map((option) => (
                    <button
                      key={option.label}
                      type="button"
                      onClick={() => {
                        setAnswers((current) => ({
                          ...current,
                          [question.id]: option.score,
                        }))
                        if ("loss" in option && option.loss)
                          setLoss(option.loss)
                      }}
                      className={`rounded-xl border p-3 text-left text-sm transition focus:outline-none focus:ring-2 focus:ring-blue-500 ${
                        answers[question.id] === option.score
                          ? "border-blue-400 bg-blue-50 text-blue-800"
                          : "border-slate-200 hover:border-blue-200"
                      }`}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
              </fieldset>
            ))}
            {errors.questionnaire && (
              <p className="text-sm font-medium text-red-600">
                {errors.questionnaire}
              </p>
            )}
            <div className="rounded-2xl border border-blue-200 bg-blue-50 p-5">
              <p className="text-xs font-bold text-blue-600">계산된 성향</p>
              <p className="mt-1 text-xl font-bold text-blue-950">{computed}</p>
              <p className="mt-2 text-sm leading-6 text-blue-900/70">
                손실 감내 수준 {loss}%와 투자 행동 응답을 바탕으로 계산한
                결과입니다. 이 수치는 미래 손실의 최대 한도를 의미하지 않습니다.
              </p>
            </div>
            <Field label="내가 최종 선택할 성향" error={errors.tendency}>
              <select
                className={inputClass}
                value={profile.finalTendency}
                onChange={(event) => {
                  setProfile((current) => ({
                    ...current,
                    finalTendency: event.target.value as Tendency,
                  }))
                  setOverrideConfirmed(event.target.value === computed)
                }}
              >
                {TENDENCIES.map((item) => (
                  <option key={item}>{item}</option>
                ))}
              </select>
            </Field>
            {profile.finalTendency !== computed && (
              <label className="flex gap-3 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950">
                <input
                  type="checkbox"
                  checked={overrideConfirmed}
                  onChange={(event) =>
                    setOverrideConfirmed(event.target.checked)
                  }
                />
                <span>
                  계산 결과는 <b>{computed}</b>이지만 최종 성향으로{" "}
                  <b>{profile.finalTendency}</b>을 선택합니다. 차이를
                  확인했습니다.
                </span>
              </label>
            )}
          </div>
        )}

        {step === 3 && (
          <div className="space-y-6">
            <div>
              <h2 className="text-lg font-bold text-slate-950">
                관심 분야와 제약
              </h2>
              <p className="mt-1 text-sm text-slate-500">
                선호는 참고 정보이고, 제외·비중 한도만 강제 조건으로 검증합니다.
              </p>
            </div>
            <Field label="관심 산업 (선택)">
              <div className="flex flex-wrap gap-2">
                {INDUSTRIES.map((item) => (
                  <button
                    key={item}
                    type="button"
                    onClick={() =>
                      setProfile((current) => ({
                        ...current,
                        industries: current.industries.includes(item)
                          ? current.industries.filter((value) => value !== item)
                          : [...current.industries, item],
                      }))
                    }
                    className={`rounded-full border px-3 py-1.5 text-xs font-semibold ${
                      profile.industries.includes(item)
                        ? "border-blue-300 bg-blue-50 text-blue-700"
                        : "border-slate-200 text-slate-600"
                    }`}
                  >
                    {item}
                  </button>
                ))}
              </div>
            </Field>
            <Field label="투자 선호">
              <div className="flex flex-wrap gap-2">
                {PREFERENCES.map((item) => (
                  <button
                    key={item}
                    type="button"
                    onClick={() =>
                      setProfile((current) => ({
                        ...current,
                        preferences: current.preferences.includes(item)
                          ? current.preferences.filter(
                              (value) => value !== item,
                            )
                          : [...current.preferences, item],
                      }))
                    }
                    className={`rounded-full border px-3 py-1.5 text-xs font-semibold ${
                      profile.preferences.includes(item)
                        ? "border-blue-300 bg-blue-50 text-blue-700"
                        : "border-slate-200 text-slate-600"
                    }`}
                  >
                    {item}
                  </button>
                ))}
              </div>
            </Field>
            <Field
              label="선호 메모"
              help="메모는 분석 참고 정보이며 자동으로 검증되는 강제 조건이 아닙니다."
            >
              <textarea
                className={`${inputClass} min-h-24 resize-none`}
                value={profile.memo}
                onChange={(event) =>
                  setProfile((current) => ({
                    ...current,
                    memo: event.target.value,
                  }))
                }
                placeholder="예: 성장성을 선호하지만 특정 산업에 과도하게 집중하고 싶지 않습니다."
              />
            </Field>
            <button
              type="button"
              onClick={() => setAdvanced((value) => !value)}
              className="flex w-full items-center justify-between rounded-xl border border-slate-200 bg-slate-50 p-4 text-left text-sm font-bold text-slate-800"
            >
              세부 조건 추가{" "}
              <ChevronDown
                className={`size-4 transition ${advanced ? "rotate-180" : ""}`}
              />
            </button>
            {advanced && (
              <div className="space-y-5 rounded-2xl border border-slate-200 p-5">
                <Field
                  label="제외 종목 검색"
                  help="회사명 또는 종목코드로 검색하세요. 분석 가능한 투자 대상만 선택할 수 있습니다."
                >
                  <input
                    className={inputClass}
                    value={securitySearch}
                    onChange={(event) => setSecuritySearch(event.target.value)}
                    placeholder="예: NVIDIA 또는 NVDA"
                  />
                  {securitySearch && (
                    <div className="mt-2 overflow-hidden rounded-xl border border-slate-200">
                      {filtered.map((security) => (
                        <button
                          key={security.ticker}
                          type="button"
                          onClick={() => {
                            setProfile((current) => ({
                              ...current,
                              excludedTickers: current.excludedTickers.includes(
                                security.ticker,
                              )
                                ? current.excludedTickers
                                : [...current.excludedTickers, security.ticker],
                              securityCaps: Object.fromEntries(
                                Object.entries(current.securityCaps).filter(
                                  ([ticker]) => ticker !== security.ticker,
                                ),
                              ),
                            }))
                            setSecuritySearch("")
                          }}
                          className="flex w-full items-center justify-between border-b border-slate-100 px-3 py-2 text-left text-sm last:border-0 hover:bg-slate-50"
                        >
                          <span>{security.name}</span>
                          <b>{security.ticker}</b>
                        </button>
                      ))}
                    </div>
                  )}
                </Field>
                <div className="flex flex-wrap gap-2">
                  {profile.excludedTickers.map((ticker) => (
                    <Badge key={ticker} tone="red">
                      {ticker}
                      <button
                        type="button"
                        aria-label={`${ticker} 제외 해제`}
                        onClick={() =>
                          setProfile((current) => ({
                            ...current,
                            excludedTickers: current.excludedTickers.filter(
                              (value) => value !== ticker,
                            ),
                          }))
                        }
                      >
                        <X className="size-3" />
                      </button>
                    </Badge>
                  ))}
                </div>
                <Field
                  label="공통 종목당 최대 비중"
                  error={errors.globalCapPct}
                >
                  <div className="relative">
                    <input
                      className={`${inputClass} pr-8`}
                      type="number"
                      value={profile.globalCapPct}
                      onChange={(event) =>
                        setProfile((current) => ({
                          ...current,
                          globalCapPct: Number(event.target.value),
                        }))
                      }
                    />
                    <span className="absolute right-3 top-2.5 text-sm text-slate-500">
                      %
                    </span>
                  </div>
                </Field>
                <Field
                  label="종목별 최대 비중"
                  help="분석 가능한 종목을 선택한 뒤 공통 한도 이하로 설정하세요."
                >
                  <div className="grid grid-cols-[1fr_120px_auto] gap-2">
                    <select
                      id="cap-ticker"
                      className={inputClass}
                      defaultValue=""
                    >
                      <option value="" disabled>
                        종목 선택
                      </option>
                      {SECURITIES.filter(
                        (item) =>
                          !profile.excludedTickers.includes(item.ticker),
                      ).map((item) => (
                        <option key={item.ticker} value={item.ticker}>
                          {item.name} ({item.ticker})
                        </option>
                      ))}
                    </select>
                    <input
                      id="cap-value"
                      className={inputClass}
                      type="number"
                      defaultValue={10}
                    />
                    <Button
                      variant="secondary"
                      onClick={() => {
                        const ticker = (document.getElementById(
                          "cap-ticker",
                        ) as HTMLSelectElement).value
                        const cap = Number(
                          (document.getElementById(
                            "cap-value",
                          ) as HTMLInputElement).value,
                        )
                        if (ticker)
                          setProfile((current) => ({
                            ...current,
                            securityCaps: {
                              ...current.securityCaps,
                              [ticker]: cap,
                            },
                          }))
                      }}
                    >
                      추가
                    </Button>
                  </div>
                </Field>
                {Object.entries(profile.securityCaps).map(([ticker, cap]) => (
                  <div
                    key={ticker}
                    className="flex items-center justify-between rounded-lg bg-slate-50 px-3 py-2 text-sm"
                  >
                    <span>
                      <b>{ticker}</b> 최대 {cap}%
                    </span>
                    <button
                      type="button"
                      className="text-slate-400"
                      onClick={() =>
                        setProfile((current) => ({
                          ...current,
                          securityCaps: Object.fromEntries(
                            Object.entries(current.securityCaps).filter(
                              ([key]) => key !== ticker,
                            ),
                          ),
                        }))
                      }
                    >
                      <X className="size-4" />
                    </button>
                    {errors[`cap-${ticker}`] && (
                      <span className="text-xs text-red-600">
                        {errors[`cap-${ticker}`]}
                      </span>
                    )}
                  </div>
                ))}
                <label className="flex items-start gap-3 rounded-xl bg-slate-50 p-4 text-sm">
                  <input
                    type="checkbox"
                    checked={profile.allowEtf}
                    onChange={(event) =>
                      setProfile((current) => ({
                        ...current,
                        allowEtf: event.target.checked,
                      }))
                    }
                  />
                  <span>
                    <b>ETF 허용</b>
                    <span className="mt-1 block text-xs leading-5 text-slate-500">
                      허용한 경우에도 분석에서 지원하는 ETF만 투자 대상에
                      포함됩니다.
                    </span>
                  </span>
                </label>
              </div>
            )}
            {!setup && (
              <Alert title="변경 적용 범위" tone="warning">
                변경한 조건은 다음 분석부터 적용되며 기존 리포트와 모의투자는
                유지됩니다.
              </Alert>
            )}
            {saveError && (
              <Alert title="저장 실패" tone="error">
                {saveError}
                <div className="mt-3 flex gap-2">
                  <Button variant="danger" onClick={submit}>
                    다시 시도
                  </Button>
                  <Button variant="ghost" onClick={onCancel}>
                    취소
                  </Button>
                </div>
              </Alert>
            )}
          </div>
        )}
      </Card>
      <div className="mt-5 flex justify-between">
        <Button
          variant="ghost"
          onClick={step === 1 ? onCancel : () => setStep((value) => value - 1)}
        >
          <ArrowLeft className="size-4" />
          {step === 1 ? "취소" : "이전"}
        </Button>
        {step < 3 ? (
          <Button onClick={next}>
            다음
            <ChevronRight className="size-4" />
          </Button>
        ) : (
          <Button onClick={submit} disabled={saving}>
            {saving ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <Check className="size-4" />
            )}
            투자조건 저장
          </Button>
        )}
      </div>
    </div>
  )
}

function ProfileSummary({
  profile,
  navigate,
}: {
  profile: Profile
  navigate: (route: Route) => void
}) {
  const items = [
    ["투자 금액", format.krw(profile.amountKrw)],
    ["투자기간", format.horizon(profile.horizonMonths)],
    ["지원 시장", profile.market],
    ["손실 감내 수준", `과거 낙폭 약 ${profile.lossTolerancePct}%까지 감수`],
    ["관심 산업", profile.industries.join(", ") || "설정 없음"],
    ["선호", profile.preferences.join(", ") || "설정 없음"],
    ["제외 종목", profile.excludedTickers.join(", ") || "없음"],
    ["공통 비중 한도", format.weight(profile.globalCapPct)],
    [
      "종목별 한도",
      Object.entries(profile.securityCaps)
        .map(([key, value]) => `${key} ${value}%`)
        .join(", ") || "없음",
    ],
    [
      "ETF 허용",
      profile.allowEtf ? "허용 (지원 자산에 한함)" : "허용하지 않음",
    ],
  ]
  return (
    <div className="space-y-7">
      <PageHeader
        eyebrow="내 투자조건"
        title="저장된 기본 투자조건"
        description="분석마다 별도로 바꾼 조건은 이 기본값을 수정하지 않습니다."
        actions={
          <>
            <Button
              variant="secondary"
              onClick={() => navigate({ page: "profile", mode: "edit" })}
            >
              <Pencil className="size-4" />
              수정
            </Button>
            <Button onClick={() => navigate({ page: "profile", mode: "edit" })}>
              <RefreshCw className="size-4" />
              투자성향 다시 평가
            </Button>
          </>
        }
      />
      <Card className="p-7">
        <div className="grid grid-cols-2 gap-x-10 gap-y-6">
          <div className="col-span-2 rounded-xl border border-blue-100 bg-blue-50 p-5">
            <p className="text-xs font-bold text-blue-600">최종 투자성향</p>
            <div className="mt-1 flex items-center gap-3">
              <p className="text-xl font-bold text-blue-950">
                {profile.finalTendency}
              </p>
              {profile.tendencyOverridden && (
                <Badge tone="amber">계산 결과에서 변경</Badge>
              )}
            </div>
            <p className="mt-2 text-sm text-blue-900/70">
              계산 결과: {profile.computedTendency}
              {profile.tendencyOverridden &&
                ` · 사용자가 ${profile.finalTendency}(으)로 최종 선택`}
            </p>
          </div>
          {items.map(([label, value]) => (
            <div key={label} className="border-b border-slate-100 pb-4">
              <p className="text-xs font-semibold text-slate-400">{label}</p>
              <p className="mt-1 text-sm font-semibold text-slate-800">
                {value}
              </p>
            </div>
          ))}
          <div className="col-span-2">
            <p className="text-xs font-semibold text-slate-400">선호 메모</p>
            <p className="mt-1 text-sm leading-6 text-slate-700">
              {profile.memo || "설정 없음"}
            </p>
          </div>
        </div>
      </Card>
    </div>
  )
}

function HomeScreen({
  data,
  navigate,
  startAnalysis,
}: {
  data: AppData
  navigate: (route: Route) => void
  startAnalysis: (idea: string) => void
}) {
  const [idea, setIdea] = useState("")
  const [error, setError] = useState("")
  const profile = data.profile
  if (!profile)
    return (
      <EmptyState
        title="먼저 내 투자조건을 설정해주세요."
        description="분석에 사용할 금액, 기간, 투자성향과 제약을 저장합니다."
        action={
          <Button onClick={() => navigate({ page: "profile", mode: "setup" })}>
            투자조건 설정 시작
          </Button>
        }
      />
    )
  const submit = () => {
    if (!idea.trim()) {
      setError("분석할 투자 아이디어를 입력해주세요.")
      return
    }
    startAnalysis(idea.trim())
  }
  return (
    <div className="space-y-8">
      <div className="mx-auto max-w-4xl pt-10 text-center">
        <Badge>
          <Sparkles className="size-3" />
          개인화 투자전략
        </Badge>
        <h1 className="mt-5 text-4xl font-extrabold tracking-tight text-slate-950">
          투자 아이디어를 포트폴리오로 확인해보세요.
        </h1>
        <p className="mt-3 text-base text-slate-600">
          내 투자조건을 반영하고, 과거 데이터로 성과와 위험을 분석합니다.
        </p>
        <div className="mt-8 rounded-2xl border border-slate-200 bg-white p-3 text-left shadow-sm">
          <textarea
            value={idea}
            onChange={(event) => {
              setIdea(event.target.value)
              setError("")
            }}
            className="min-h-36 w-full resize-none rounded-xl border-0 p-3 text-base leading-7 outline-none placeholder:text-slate-400"
            placeholder="예: AI 산업에 투자하고 싶지만 NVIDIA 비중은 낮게 가져가고 싶어요."
          />
          <div className="flex items-center justify-between border-t border-slate-100 px-2 pt-3">
            <p className="text-xs text-slate-400">
              분석은 조건 확인 후에만 시작됩니다.
            </p>
            <Button onClick={submit}>
              투자조건 확인하기
              <ChevronRight className="size-4" />
            </Button>
          </div>
          {error && (
            <p className="px-2 pt-2 text-xs font-medium text-red-600">
              {error}
            </p>
          )}
        </div>
      </div>
      <div className="grid grid-cols-[1.2fr_1fr] gap-5">
        <Card className="p-6">
          <div className="flex items-start justify-between">
            <div>
              <h2 className="font-bold text-slate-900">저장된 기본 투자조건</h2>
              <p className="mt-1 text-xs text-slate-500">
                미국 시장 · 이번 분석에서만 변경할 수 있습니다.
              </p>
            </div>
            <button
              onClick={() => navigate({ page: "profile" })}
              className="text-xs font-semibold text-blue-700"
            >
              내 투자조건 수정
            </button>
          </div>
          <div className="mt-5 grid grid-cols-4 gap-3">
            {[
              ["금액", format.krw(profile.amountKrw)],
              ["기간", format.horizon(profile.horizonMonths)],
              ["성향", profile.finalTendency],
              ["손실 감내 수준", `${profile.lossTolerancePct}%`],
            ].map(([label, value]) => (
              <div key={label} className="rounded-xl bg-slate-50 p-3">
                <p className="text-[11px] text-slate-400">{label}</p>
                <p className="mt-1 truncate text-sm font-bold text-slate-800">
                  {value}
                </p>
              </div>
            ))}
          </div>
          <div className="mt-4 flex flex-wrap gap-2">
            <Badge tone="slate">종목당 최대 {profile.globalCapPct}%</Badge>
            {Object.entries(profile.securityCaps).map(([ticker, cap]) => (
              <Badge key={ticker} tone="slate">
                {ticker} 최대 {cap}%
              </Badge>
            ))}
            {profile.excludedTickers.map((ticker) => (
              <Badge key={ticker} tone="red">
                {ticker} 제외
              </Badge>
            ))}
          </div>
        </Card>
        <Card className="p-6">
          <div className="flex justify-between">
            <h2 className="font-bold text-slate-900">최근 분석 리포트</h2>
            <button
              onClick={() => navigate({ page: "reports" })}
              className="text-xs font-semibold text-blue-700"
            >
              전체 보기
            </button>
          </div>
          <div className="mt-3 space-y-1">
            {data.reports.slice(0, 3).map((report) => (
              <button
                key={report.id}
                onClick={() => navigate({ page: "report", id: report.id })}
                className="flex w-full items-center justify-between rounded-xl p-3 text-left hover:bg-slate-50"
              >
                <span>
                  <span className="block text-sm font-semibold text-slate-800">
                    {report.title}
                  </span>
                  <span className="mt-0.5 block text-xs text-slate-400">
                    {report.createdAt}
                  </span>
                </span>
                <ChevronRight className="size-4 text-slate-300" />
              </button>
            ))}
          </div>
        </Card>
      </div>
      {data.paperPortfolios.length > 0 && (
        <Card className="p-6">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="font-bold text-slate-900">모의투자 미리보기</h2>
              <p className="mt-1 text-xs text-slate-500">
                최근 확인한 모의투자 전략의 성과와 업데이트 기준일을 확인합니다.
              </p>
            </div>
            <Button
              variant="secondary"
              onClick={() => navigate({ page: "paper" })}
            >
              모의투자 보기
            </Button>
          </div>
        </Card>
      )}
    </div>
  )
}

function ConditionTable({
  profile,
  conditions,
  onChange,
}: {
  profile: Profile
  conditions: EffectiveConditions
  onChange: (conditions: EffectiveConditions) => void
}) {
  const rows = [
    [
      "투자 금액",
      format.krw(profile.amountKrw),
      format.krw(conditions.amountKrw),
      "amountKrw",
    ],
    [
      "투자기간",
      format.horizon(profile.horizonMonths),
      format.horizon(conditions.horizonMonths),
      "horizonMonths",
    ],
    [
      "투자성향",
      profile.finalTendency,
      conditions.finalTendency,
      "finalTendency",
    ],
    [
      "손실 감내 수준",
      `${profile.lossTolerancePct}%`,
      `${conditions.lossTolerancePct}%`,
      "lossTolerancePct",
    ],
    [
      "관심 산업",
      profile.industries.join(", ") || "없음",
      conditions.industries.join(", ") || "없음",
      "industries",
    ],
    [
      "선호",
      profile.preferences.join(", ") || "없음",
      conditions.preferences.join(", ") || "없음",
      "preferences",
    ],
    [
      "공통 비중 한도",
      `${profile.globalCapPct}%`,
      `${conditions.globalCapPct}%`,
      "globalCapPct",
    ],
    [
      "종목별 한도",
      Object.entries(profile.securityCaps)
        .map(([key, value]) => `${key} ${value}%`)
        .join(", ") || "없음",
      Object.entries(conditions.securityCaps)
        .map(([key, value]) => `${key} ${value}%`)
        .join(", ") || "없음",
      "securityCaps",
    ],
    [
      "제외 종목",
      profile.excludedTickers.join(", ") || "없음",
      conditions.excludedTickers.join(", ") || "없음",
      "excludedTickers",
    ],
    [
      "ETF 허용",
      profile.allowEtf ? "허용" : "불가",
      conditions.allowEtf ? "허용" : "불가",
      "allowEtf",
    ],
    [
      "명시 종목",
      "없음",
      conditions.namedTickers.join(", ") || "없음",
      "namedTickers",
    ],
  ]
  return (
    <div className="overflow-hidden rounded-xl border border-slate-200">
      <table className="w-full min-w-[640px] text-left text-sm">
        <thead className="bg-slate-50 text-xs text-slate-500">
          <tr>
            <th className="px-4 py-3">조건</th>
            <th className="px-4 py-3">저장 기본값</th>
            <th className="px-4 py-3">이번 분석 적용값</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rows.map(([label, before, after, key]) => {
            const changed =
              before !== after || conditions.analysisOverrides.includes(key)
            return (
              <tr key={label}>
                <td className="px-4 py-3 font-semibold text-slate-700">
                  {label}
                </td>
                <td className="px-4 py-3 text-slate-500">{before}</td>
                <td className="px-4 py-3 text-slate-800">
                  <div className="flex items-center gap-2">
                    {after}
                    {changed && <Badge tone="amber">이번 분석만 변경</Badge>}
                  </div>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
      <div className="border-t border-slate-100 bg-slate-50 p-4">
        <div className="grid grid-cols-3 gap-3">
          <Field label="이번 분석 금액">
            <input
              className={inputClass}
              type="number"
              value={conditions.amountKrw}
              onChange={(event) =>
                onChange({
                  ...conditions,
                  amountKrw: Number(event.target.value),
                  analysisOverrides: [
                    ...new Set([...conditions.analysisOverrides, "amountKrw"]),
                  ],
                })
              }
            />
          </Field>
          <Field label="이번 분석 기간(개월)">
            <input
              className={inputClass}
              type="number"
              value={conditions.horizonMonths}
              onChange={(event) =>
                onChange({
                  ...conditions,
                  horizonMonths: Number(event.target.value),
                  analysisOverrides: [
                    ...new Set([
                      ...conditions.analysisOverrides,
                      "horizonMonths",
                    ]),
                  ],
                })
              }
            />
          </Field>
          <Field label="공통 비중 한도(%)">
            <input
              className={inputClass}
              type="number"
              value={conditions.globalCapPct}
              onChange={(event) =>
                onChange({
                  ...conditions,
                  globalCapPct: Number(event.target.value),
                  analysisOverrides: [
                    ...new Set([
                      ...conditions.analysisOverrides,
                      "globalCapPct",
                    ]),
                  ],
                })
              }
            />
          </Field>
        </div>
      </div>
    </div>
  )
}

function ReviewScreen({
  profile,
  draft,
  setDraft,
  run,
  navigate,
}: {
  profile: Profile
  draft: AnalysisDraft
  setDraft: (draft: AnalysisDraft) => void
  run: () => void
  navigate: (route: Route) => void
}) {
  const [answer, setAnswer] = useState("")
  const [editingIdea, setEditingIdea] = useState(false)
  const namedNvda = /nvidia|엔비디아|NVDA/i.test(draft.idea)
  const asksLow = /낮|제한|적게/i.test(draft.idea)
  const unresolved =
    namedNvda && asksLow && draft.conditions.securityCaps.NVDA === undefined
  const infeasible = draft.conditions.globalCapPct * 5 < 100
  const question = unresolved ? "NVIDIA 비중을 몇 % 이하로 제한할까요?" : null
  const answerQuestion = () => {
    const cap = Number(answer)
    if (!Number.isFinite(cap) || cap < 0 || cap > draft.conditions.globalCapPct)
      return
    setDraft({
      ...draft,
      answers: [...draft.answers, { question: question!, answer: `${cap}%` }],
      clarificationCount: draft.clarificationCount + 1,
      conditions: {
        ...draft.conditions,
        securityCaps: { ...draft.conditions.securityCaps, NVDA: cap },
        namedTickers: [...new Set([...draft.conditions.namedTickers, "NVDA"])],
        analysisOverrides: [
          ...new Set([
            ...draft.conditions.analysisOverrides,
            "securityCaps",
            "namedTickers",
          ]),
        ],
      },
    })
    setAnswer("")
  }
  const exhausted =
    draft.clarificationCount >= APP_CONFIG.clarificationLimit && unresolved
  return (
    <div className="space-y-7">
      <PageHeader
        eyebrow="분석 전 확인"
        title="요청을 해석하고 조건을 확인했습니다."
        description="저장된 조건을 다시 묻지 않고, 모호하거나 충돌하는 항목만 한 번에 하나씩 확인합니다."
      />
      <div className="grid grid-cols-[0.9fr_1.3fr] gap-6">
        <Card className="p-6">
          <h2 className="font-bold text-slate-900">원래 요청과 확인 대화</h2>
          {editingIdea ? (
            <textarea
              className={`${inputClass} mt-4 min-h-36`}
              value={draft.idea}
              onChange={(event) =>
                setDraft({ ...draft, idea: event.target.value })
              }
            />
          ) : (
            <blockquote className="mt-4 rounded-xl bg-slate-50 p-4 text-sm leading-7 text-slate-700">
              “{draft.idea}”
            </blockquote>
          )}
          <button
            onClick={() => setEditingIdea((value) => !value)}
            className="mt-2 text-xs font-semibold text-blue-700"
          >
            {editingIdea ? "수정 완료" : "요청 수정"}
          </button>
          {draft.answers.map((item) => (
            <div key={item.question} className="mt-4 space-y-2">
              <div className="rounded-xl bg-slate-100 p-3 text-sm text-slate-700">
                {item.question}
              </div>
              <div className="ml-8 rounded-xl bg-blue-700 p-3 text-sm text-white">
                {item.answer}
              </div>
            </div>
          ))}
          {question && !exhausted && (
            <div className="mt-5 rounded-xl border border-blue-200 bg-blue-50 p-4">
              <p className="text-sm font-semibold text-blue-950">{question}</p>
              <p className="mt-1 text-xs text-blue-700">
                지원 범위: 0~{draft.conditions.globalCapPct}%
              </p>
              <div className="mt-3 flex gap-2">
                <input
                  className={inputClass}
                  type="number"
                  min={0}
                  max={draft.conditions.globalCapPct}
                  value={answer}
                  onChange={(event) => setAnswer(event.target.value)}
                  placeholder="예: 10"
                />
                <Button onClick={answerQuestion}>답변 적용</Button>
              </div>
            </div>
          )}
          {exhausted && (
            <Alert title="확인할 수 없는 조건이 남았습니다." tone="error">
              NVIDIA 최대 비중을 확정하지 못했습니다. 예: “NVIDIA 비중은 10%
              이하로 해주세요.”처럼 요청을 수정해주세요.
            </Alert>
          )}
        </Card>
        <Card className="p-6">
          <div className="mb-4 flex items-center justify-between">
            <div>
              <h2 className="font-bold text-slate-900">
                이번 분석에 적용할 조건
              </h2>
              <p className="mt-1 text-xs text-slate-500">
                변경값은 저장된 기본 프로필을 수정하지 않습니다.
              </p>
            </div>
            <Badge tone="slate">지원 시장: 미국</Badge>
          </div>
          <ConditionTable
            profile={profile}
            conditions={draft.conditions}
            onChange={(conditions) => setDraft({ ...draft, conditions })}
          />
          {infeasible && (
            <div className="mt-4">
              <Alert
                title="현재 비중 한도로 5개 종목을 100% 구성할 수 없습니다."
                tone="error"
              >
                종목당 {draft.conditions.globalCapPct}% 한도 × 5개 ={" "}
                {draft.conditions.globalCapPct * 5}%입니다. 한도를 높이거나 선택
                종목 수를 늘려주세요.
              </Alert>
            </div>
          )}
        </Card>
      </div>
      <div className="flex justify-between">
        <Button variant="ghost" onClick={() => navigate({ page: "home" })}>
          종료
        </Button>
        <div className="flex gap-2">
          <Button variant="secondary" onClick={() => setEditingIdea(true)}>
            요청 수정
          </Button>
          <Button
            disabled={Boolean(unresolved) || exhausted || infeasible}
            onClick={run}
          >
            <Play className="size-4" />이 조건으로 분석하기
          </Button>
        </div>
      </div>
    </div>
  )
}

const RUN_STAGES = [
  "투자조건 확인",
  "데이터 조회와 후보 탐색",
  "전략 구성과 조건 검증",
  "백테스트와 후보 평가",
  "근거 확인과 리포트 생성",
]
const failureCopy: Record<Exclude<DemoOutcome, "success" | "partial" | "save-failure">, {
  stage: string
  reason: string
  detail: string
}> = {
  "required-data": {
    stage: "데이터 조회와 후보 탐색",
    reason: "필수 비교지수 가격 데이터를 찾을 수 없습니다.",
    detail:
      "비교지수 가격은 같은 기간의 성과를 계산하는 데 필요합니다. 자료를 확인한 뒤 다시 시도해주세요.",
  },
  infeasible: {
    stage: "전략 구성과 조건 검증",
    reason: "모든 사용자 제약을 동시에 만족하는 비중이 없습니다.",
    detail:
      "조건을 자동으로 완화하지 않았습니다. 비중 한도 또는 제외 종목을 수정해주세요.",
  },
  backtest: {
    stage: "백테스트와 후보 평가",
    reason: "가격자료의 연속 결측 구간이 허용 범위를 넘었습니다.",
    detail: "누락된 거래일 자료를 확인한 뒤 다시 시도해주세요.",
  },
  consistency: {
    stage: "근거 확인과 리포트 생성",
    reason: "리포트의 배분 금액과 초기자본이 일치하지 않습니다.",
    detail: "검증되지 않은 결과는 정상 리포트로 표시하지 않습니다.",
  },
}

function RunScreen({
  draft,
  outcome,
  onComplete,
  onCancel,
  onEdit,
}: {
  draft: AnalysisDraft
  outcome: DemoOutcome
  onComplete: (report: Report, saveFailure: boolean) => void
  onCancel: () => void
  onEdit: () => void
}) {
  const [active, setActive] = useState(0)
  const [canceled, setCanceled] = useState(false)
  const [failed, setFailed] = useState(false)
  const completedRef = useRef(false)
  useEffect(() => {
    if (canceled || failed || completedRef.current) return
    const fail = !["success", "partial", "save-failure"].includes(outcome)
    if (
      fail &&
      active ===
        RUN_STAGES.indexOf(
          failureCopy[(outcome as keyof typeof failureCopy)].stage,
        )
    ) {
      const timer = window.setTimeout(() => setFailed(true), 800)
      return () => window.clearTimeout(timer)
    }
    if (active >= RUN_STAGES.length) {
      completedRef.current = true
      const report = makeDemoReport(
        `report-${Date.now()}`,
        draft.mode === "revision" ? "수정된 AI 분산 전략" : "새 AI 분산 전략",
        draft.idea,
      )
      report.createdAt = APP_CONFIG.canonicalAsOf
      report.conditions = structuredClone(draft.conditions)
      report.status = outcome === "partial" ? "partial" : "complete"
      if (draft.mode === "revision") {
        report.series = report.series.map((point, index) => ({
          ...point,
          portfolio:
            index === 0
              ? point.portfolio
              : point.portfolio * (1 - index * 0.002),
          drawdown: Math.min(0, point.drawdown + (index === 4 ? 2.1 : 0.4)),
        }))
        report.metrics = calculateMetrics(report.series)
      }
      if (outcome !== "partial") {
        report.exclusions = []
        report.execution = report.execution.map((item) => ({
          ...item,
          issues: [],
        }))
      }
      if (draft.sourceReportId) report.sourceReportId = draft.sourceReportId
      onComplete(report, outcome === "save-failure")
      return
    }
    const timer = window.setTimeout(() => setActive((value) => value + 1), 800)
    return () => window.clearTimeout(timer)
  }, [active, canceled, draft, failed, onComplete, outcome])
  const cancel = () => {
    setCanceled(true)
    onCancel()
  }
  if (canceled)
    return (
      <EmptyState
        title="분석을 취소했습니다."
        description="리포트는 생성하지 않았습니다. 요청과 확정 조건은 보존되어 다시 시도할 수 있습니다."
        action={
          <div className="flex gap-2">
            <Button variant="secondary" onClick={onEdit}>
              조건 수정
            </Button>
            <Button
              onClick={() => {
                setCanceled(false)
                setActive(0)
                completedRef.current = false
              }}
            >
              다시 시도
            </Button>
          </div>
        }
      />
    )
  if (failed) {
    const copy = failureCopy[(outcome as keyof typeof failureCopy)]
    return (
      <div className="mx-auto max-w-3xl space-y-6 pt-16">
        <Badge tone="red">
          <AlertCircle className="size-3" />
          분석 실패
        </Badge>
        <PageHeader title={copy.stage} description={copy.reason} />
        <Alert title="분석을 중단했습니다." tone="error">
          {copy.detail}
        </Alert>
        <Card className="p-6">
          <h2 className="font-bold text-slate-900">실행 상태</h2>
          <div className="mt-4 space-y-3">
            {RUN_STAGES.map((stage, index) => (
              <StatusRow
                key={stage}
                label={stage}
                status={
                  index < active
                    ? "completed"
                    : index === active
                      ? "failed"
                      : "skipped"
                }
              />
            ))}
          </div>
        </Card>
        <div className="flex gap-2">
          <Button variant="secondary" onClick={onEdit}>
            조건 수정
          </Button>
          <Button
            onClick={() => {
              setActive(0)
              setFailed(false)
              completedRef.current = false
            }}
          >
            다시 시도
          </Button>
          <Button
            variant="ghost"
            onClick={() => (window.location.hash = "#/home")}
          >
            종료
          </Button>
        </div>
      </div>
    )
  }
  return (
    <div className="mx-auto max-w-4xl space-y-7 pt-10">
      <PageHeader
        eyebrow="투자전략 분석"
        title="투자 아이디어와 적용 조건을 분석하고 있습니다."
        description="자료 검토, 전략 구성, 과거 성과 계산을 차례로 진행합니다."
      />
      <div className="grid grid-cols-[1.2fr_0.8fr] gap-6">
        <Card className="p-6">
          <div className="space-y-4">
            {RUN_STAGES.map((stage, index) => (
              <StatusRow
                key={stage}
                label={stage}
                status={
                  index < active
                    ? outcome === "partial" && index === 1
                      ? "partial"
                      : "completed"
                    : index === active
                      ? "processing"
                      : "waiting"
                }
                detail={
                  index < active
                    ? [
                        "저장값과 이번 분석 변경 조건을 확인했습니다.",
                        "투자 대상과 자료의 분석기간을 확인했습니다.",
                        "네 가지 후보전략을 구성하고 투자조건을 검증했습니다.",
                        "같은 기간·비용으로 후보를 비교했습니다.",
                        "수치 일관성을 확인하고 리포트를 구성했습니다.",
                      ][index]
                    : undefined
                }
              />
            ))}
          </div>
        </Card>
        <div className="space-y-4">
          <Card className="p-5">
            <p className="text-xs font-bold text-slate-400">현재 단계</p>
            <p className="mt-2 font-bold text-slate-900">
              {RUN_STAGES[Math.min(active, 4)]}
            </p>
            <p className="mt-2 text-sm leading-6 text-slate-500">
              현재 단계가 끝나면 다음 단계로 자동으로 이동합니다.
            </p>
          </Card>
          <Card className="p-5">
            <p className="text-xs font-bold text-slate-400">후보전략 평가</p>
            <p className="mt-2 text-sm leading-6 text-slate-600">
              조건 검증을 통과한 후보를 동일한 비교 조건으로 평가합니다. 실패
              조건 검증을 통과한 후보를 같은 기간과 비용 기준으로 비교합니다.
              검증에 계속 실패한 후보는 결과에서 제외합니다.
            </p>
          </Card>
        </div>
      </div>
      <div className="flex items-center justify-end">
        <Button variant="danger" onClick={cancel}>
          <X className="size-4" />
          분석 취소
        </Button>
      </div>
    </div>
  )
}

function StatusRow({
  label,
  status,
  detail,
}: {
  label: string
  status: StageStatus
  detail?: string
}) {
  const map: Record<StageStatus, {
    label: string
    icon: React.ElementType
    classes: string
  }> = {
    waiting: { label: "대기", icon: Circle, classes: "text-slate-400" },
    processing: { label: "처리 중", icon: Loader2, classes: "text-blue-700" },
    completed: { label: "완료", icon: Check, classes: "text-emerald-700" },
    partial: {
      label: "일부 제외 후 완료",
      icon: AlertTriangle,
      classes: "text-amber-700",
    },
    failed: { label: "실패", icon: AlertCircle, classes: "text-red-700" },
    canceled: { label: "취소", icon: X, classes: "text-slate-600" },
    skipped: {
      label: "이전 실패로 미실행",
      icon: Circle,
      classes: "text-slate-400",
    },
  }
  const item = map[status]
  return (
    <div className="flex items-start gap-3">
      <item.icon
        className={`mt-0.5 size-5 shrink-0 ${item.classes} ${
          status === "processing" ? "animate-spin" : ""
        }`}
      />
      <div className="flex-1">
        <div className="flex items-center justify-between">
          <p
            className={`text-sm font-semibold ${
              status === "waiting" || status === "skipped"
                ? "text-slate-400"
                : "text-slate-800"
            }`}
          >
            {label}
          </p>
          <span className={`text-xs font-semibold ${item.classes}`}>
            {item.label}
          </span>
        </div>
        {detail && <p className="mt-1 text-xs text-slate-500">{detail}</p>}
      </div>
    </div>
  )
}

function ReportList({
  reports,
  navigate,
}: {
  reports: Report[]
  navigate: (route: Route) => void
}) {
  const [query, setQuery] = useState("")
  const [state, setState] = useState<"ready" | "loading" | "error">("ready")
  const filtered = reports
    .filter((report) =>
      `${report.title} ${report.idea} ${report.allocation.map((item) => `${item.company} ${item.ticker}`).join(" ")}`
        .toLowerCase()
        .includes(query.toLowerCase()),
    )
    .sort((a, b) => b.createdAt.localeCompare(a.createdAt))
  if (state === "loading")
    return (
      <div className="space-y-4">
        {[1, 2, 3].map((item) => (
          <div
            key={item}
            className="h-36 animate-pulse rounded-2xl bg-slate-200"
          />
        ))}
      </div>
    )
  if (state === "error")
    return (
      <EmptyState
        title="저장된 리포트를 불러오지 못했습니다."
        description="다시 시도하거나 홈으로 이동해주세요."
        action={<Button onClick={() => setState("ready")}>다시 시도</Button>}
      />
    )
  return (
    <div className="space-y-7">
      <PageHeader
        eyebrow="분석 리포트"
        title="저장된 분석 리포트"
        description="각 리포트는 분석 당시의 투자조건과 자료, 포트폴리오 구성을 그대로 보존합니다."
        actions={
          <Button onClick={() => navigate({ page: "home" })}>
            <Plus className="size-4" />새 분석
          </Button>
        }
      />
      <div className="relative">
        <Search className="absolute left-3 top-3 size-4 text-slate-400" />
        <input
          className={`${inputClass} pl-10`}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="제목, 투자 아이디어, 회사명 또는 종목코드 검색"
        />
      </div>
      {filtered.length === 0 ? (
        <EmptyState
          title="저장된 리포트가 없습니다."
          description="첫 투자 아이디어를 분석하면 완료된 리포트가 여기에 표시됩니다."
          action={
            <Button onClick={() => navigate({ page: "home" })}>
              첫 분석 시작하기
            </Button>
          }
        />
      ) : (
        <div className="space-y-3">
          {filtered.map((report) => (
            <Card key={report.id} className="p-5">
              <div className="flex items-start justify-between gap-8">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <h2 className="font-bold text-slate-900">{report.title}</h2>
                    {report.status === "partial" && (
                      <Badge tone="amber">일부 제외</Badge>
                    )}
                  </div>
                  <p className="mt-2 truncate text-sm text-slate-600">
                    {report.idea}
                  </p>
                  <div className="mt-4 flex flex-wrap gap-x-6 gap-y-2 text-xs text-slate-500">
                    <span>생성 {report.createdAt}</span>
                    <span>
                      {format.krw(report.conditions.amountKrw)} ·{" "}
                      {format.horizon(report.conditions.horizonMonths)} ·{" "}
                      {report.conditions.finalTendency}
                    </span>
                    <span>시장 기준일 {report.calculation.marketAsOf}</span>
                    <span>
                      {report.conditions.namedTickers.join(", ") ||
                        "명시 종목 없음"}
                    </span>
                  </div>
                </div>
                <div className="text-right">
                  <Badge tone={report.saved ? "green" : "red"}>
                    {report.saved ? "저장됨" : "저장되지 않음"}
                  </Badge>
                  <div className="mt-3">
                    <Button
                      variant="secondary"
                      onClick={() =>
                        navigate({ page: "report", id: report.id })
                      }
                    >
                      리포트 보기
                    </Button>
                  </div>
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}
      <p className="text-center text-xs text-slate-400">최신 분석순</p>
    </div>
  )
}

function MetricCard({
  label,
  value,
  note,
  danger,
}: {
  label: string
  value: string
  note?: string
  danger?: boolean
}) {
  return (
    <div
      className={`rounded-xl border p-4 ${
        danger ? "border-amber-200 bg-amber-50" : "border-slate-200 bg-white"
      }`}
    >
      <p className="text-xs font-semibold text-slate-500">{label}</p>
      <p
        className={`mt-1 text-xl font-bold tabular-nums ${
          danger ? "text-amber-800" : "text-slate-950"
        }`}
      >
        {value}
      </p>
      {note && (
        <p className="mt-1 text-[11px] leading-4 text-slate-500">{note}</p>
      )}
    </div>
  )
}

function ReportDetail({
  report,
  fresh,
  navigate,
  startTracking,
  reanalyze,
  revise,
  retrySave,
}: {
  report: Report
  fresh: boolean
  navigate: (route: Route) => void
  startTracking: () => void
  reanalyze: () => void
  revise: () => void
  retrySave: () => void
}) {
  const [stock, setStock] = useState<string | null>(null)
  const [source, setSource] = useState<Evidence | null>(null)
  const [logs, setLogs] = useState(false)
  const selected = report.allocation.find((item) => item.ticker === stock)
  const metrics = report.metrics
  const evidenceNumber = (id: string) =>
    report.evidence.findIndex((item) => item.id === id) + 1
  const evidenceById = (id: string) =>
    report.evidence.find((item) => item.id === id)
  const prose = (
    paragraph: { text: string citationIds: string[] },
    key: string,
  ) => (
    <p key={key} className="max-w-4xl text-[15px] leading-8 text-slate-700">
      {paragraph.text}
      {paragraph.citationIds.map((id) => {
        const item = evidenceById(id)
        if (!item) return null
        return (
          <button
            key={id}
            aria-label={`참고자료 ${evidenceNumber(id)} 보기`}
            onClick={() => setSource(item)}
            className="ml-1 align-super text-[11px] font-bold text-blue-700 hover:underline"
          >
            [{evidenceNumber(id)}]
          </button>
        )
      })}
    </p>
  )
  const sections = [
    ["judgment", "종합 투자 판단"],
    ["industry", "산업과 시장 분석"],
    ["companies", "기업별 투자 근거"],
    ["construction", "포트폴리오 구성과 운용"],
    ["performance", "과거 성과와 해석"],
    ["reconsideration", "판단의 전제와 재검토 조건"],
    ["references", "참고자료와 분석 조건"],
    ["analysis-log", "분석Log"],
  ]

  return (
    <div className="space-y-6">
      {!report.saved && (
        <Alert title="리포트가 저장되지 않았습니다." tone="error">
          분석 결과는 그대로 확인할 수 있습니다.
          <div className="mt-3">
            <Button variant="danger" onClick={retrySave}>
              저장 다시 시도
            </Button>
          </div>
        </Alert>
      )}
      <PageHeader
        eyebrow={`투자전략 리포트 · ${report.createdAt}`}
        title={report.title}
        description={report.idea}
        actions={
          <>
            <Button variant="secondary" onClick={revise}>
              조건 수정 후 재분석
            </Button>
            {fresh ? (
              <Button onClick={startTracking}>
                <Activity className="size-4" />이 전략으로 모의투자 시작
              </Button>
            ) : (
              <Button onClick={reanalyze}>
                <RefreshCw className="size-4" />
                같은 조건으로 재분석
              </Button>
            )}
          </>
        }
      />
      {!fresh && (
        <p className="text-right text-xs text-slate-500">
          모의투자는 새 분석을 완료한 뒤 시작할 수 있습니다.
        </p>
      )}

      <nav
        className="sticky top-0 z-10 flex gap-1 overflow-x-auto rounded-xl border border-slate-200 bg-white/95 p-1.5 shadow-sm backdrop-blur"
        aria-label="리포트 내 이동"
      >
        {sections.map(([id, label]) => (
          <button
            key={id}
            onClick={() =>
              document
                .getElementById(id)
                ?.scrollIntoView({ behavior: "smooth", block: "start" })
            }
            className="whitespace-nowrap rounded-lg px-3 py-2 text-xs font-semibold text-slate-600 hover:bg-blue-50 hover:text-blue-700"
          >
            {label}
          </button>
        ))}
      </nav>

      <article className="rounded-2xl border border-slate-200 bg-white px-10 py-10 shadow-sm">
        <section
          id="judgment"
          className="scroll-mt-20 border-b border-slate-200 pb-12"
        >
          <div className="flex items-start justify-between gap-8">
            <div>
              <p className="text-xs font-bold tracking-widest text-blue-700">
                투자전략 검토
              </p>
              <h2 className="mt-2 text-2xl font-bold tracking-tight text-slate-950">
                종합 투자 판단
              </h2>
            </div>
            <div className="grid shrink-0 grid-cols-3 gap-5 text-right text-xs">
              <div>
                <p className="text-slate-400">리포트 작성일</p>
                <p className="mt-1 font-semibold text-slate-700">
                  {report.createdAt}
                </p>
              </div>
              <div>
                <p className="text-slate-400">분석 기준일</p>
                <p className="mt-1 font-semibold text-slate-700">
                  {report.calculation.marketAsOf}
                </p>
              </div>
              <div>
                <p className="text-slate-400">투자기간</p>
                <p className="mt-1 font-semibold text-slate-700">
                  {format.horizon(report.conditions.horizonMonths)}
                </p>
              </div>
            </div>
          </div>
          <div className="mt-8 space-y-5">
            {report.narrative.overallJudgment.map((item, index) =>
              prose(item, `overall-${index}`),
            )}
          </div>
          <div className="mt-8 grid grid-cols-4 gap-3">
            <MetricCard
              label="누적 수익률"
              value={format.pct(metrics.cumulativeReturn, true)}
              note={`${report.calculation.startDate}~${report.calculation.endDate}`}
            />
            <MetricCard
              label="비교지수 수익률"
              value={format.pct(metrics.benchmarkReturn, true)}
              note={report.calculation.benchmark}
            />
            <MetricCard
              label="연환산 변동성"
              value={
                metrics.volatility == null
                  ? "산출 불가"
                  : format.pct(metrics.volatility)
              }
            />
            <MetricCard
              label="최대 낙폭(MDD)"
              value={format.pct(metrics.mdd)}
              note={`손실 감내 수준 ${report.conditions.lossTolerancePct}%`}
            />
          </div>
          <details className="mt-7 rounded-xl border border-slate-200 bg-slate-50 px-5 py-4">
            <summary className="text-sm font-semibold text-slate-800">
              이번 분석에 적용한 투자조건
            </summary>
            <div className="mt-4 grid grid-cols-4 gap-x-6 gap-y-4 text-sm">
              {[
                ["투자금액", format.krw(report.conditions.amountKrw)],
                ["투자기간", format.horizon(report.conditions.horizonMonths)],
                ["투자성향", report.conditions.finalTendency],
                ["손실 감내 수준", `${report.conditions.lossTolerancePct}%`],
                ["관심 산업", report.conditions.industries.join(", ")],
                ["종목당 한도", `${report.conditions.globalCapPct}%`],
                [
                  "종목별 한도",
                  Object.entries(report.conditions.securityCaps)
                    .map(([key, value]) => `${key} ${value}%`)
                    .join(", ") || "없음",
                ],
                ["ETF", report.conditions.allowEtf ? "허용" : "제외"],
              ].map(([label, value]) => (
                <div key={label}>
                  <p className="text-xs text-slate-400">{label}</p>
                  <p className="mt-1 font-semibold text-slate-700">{value}</p>
                </div>
              ))}
            </div>
          </details>
        </section>

        <section
          id="industry"
          className="scroll-mt-20 border-b border-slate-200 py-12"
        >
          <p className="text-xs font-bold tracking-widest text-blue-700">01</p>
          <h2 className="mt-2 text-2xl font-bold tracking-tight text-slate-950">
            산업과 시장 분석
          </h2>
          <div className="mt-7 space-y-5">
            {report.narrative.industryAnalysis.map((item, index) =>
              prose(item, `industry-${index}`),
            )}
          </div>
        </section>

        <section
          id="companies"
          className="scroll-mt-20 border-b border-slate-200 py-12"
        >
          <p className="text-xs font-bold tracking-widest text-blue-700">02</p>
          <h2 className="mt-2 text-2xl font-bold tracking-tight text-slate-950">
            기업별 투자 근거
          </h2>
          <div className="mt-8 divide-y divide-slate-200">
            {report.narrative.companyAnalyses.map((company) => {
              const allocation = report.allocation.find(
                (item) => item.ticker === company.ticker,
              )
              return (
                <section key={company.ticker} className="py-8 first:pt-0">
                  <div className="flex items-start justify-between gap-8">
                    <div>
                      <h3 className="text-lg font-bold text-slate-950">
                        {company.heading}
                      </h3>
                      <p className="mt-1 text-xs font-semibold text-slate-400">
                        {company.ticker}
                      </p>
                    </div>
                    {allocation && (
                      <button
                        onClick={() => setStock(company.ticker)}
                        className="shrink-0 rounded-xl border border-slate-200 px-4 py-2 text-right hover:border-blue-300 hover:bg-blue-50"
                      >
                        <span className="block text-[11px] text-slate-400">
                          배분 비중
                        </span>
                        <span className="text-base font-bold text-blue-700">
                          {format.weight(allocation.weight)}
                        </span>
                      </button>
                    )}
                  </div>
                  <div className="mt-5 space-y-5">
                    {company.paragraphs.map((item, index) =>
                      prose(item, `${company.ticker}-${index}`),
                    )}
                  </div>
                </section>
              )
            })}
          </div>
        </section>

        <section
          id="construction"
          className="scroll-mt-20 border-b border-slate-200 py-12"
        >
          <p className="text-xs font-bold tracking-widest text-blue-700">03</p>
          <h2 className="mt-2 text-2xl font-bold tracking-tight text-slate-950">
            포트폴리오 구성과 운용
          </h2>
          <div className="mt-7 space-y-5">
            {report.narrative.portfolioConstruction.map((item, index) =>
              prose(item, `construction-${index}`),
            )}
          </div>
          <div className="mt-9">
            <div className="flex items-end justify-between gap-6">
              <div>
                <h3 className="text-base font-bold text-slate-900">
                  후보전략 비교와 최종 선택
                </h3>
                <p className="mt-1 max-w-3xl text-sm leading-6 text-slate-600">
                  선정 규칙, 배분 방식, 재조정 주기를 달리한 후보를 같은 기간과
                  거래비용으로 비교했습니다. 최종안은 수익률 한 항목이 아니라
                  투자조건 충족 여부와 변동성, 최대 낙폭, 위험조정 성과를 함께
                  고려해 선택했습니다.
                </p>
              </div>
              <Badge tone="blue">
                {report.candidateStrategies.length}개 전략 비교
              </Badge>
            </div>
            <div className="mt-5 overflow-x-auto rounded-xl border border-slate-200">
              <table className="w-full min-w-[960px] text-left text-sm">
                <thead className="bg-slate-50 text-xs text-slate-500">
                  <tr>
                    <th className="px-4 py-3">후보전략</th>
                    <th className="px-4 py-3">종목 선정</th>
                    <th className="px-4 py-3">비중 배분</th>
                    <th className="px-4 py-3 text-right">누적수익률</th>
                    <th className="px-4 py-3 text-right">변동성</th>
                    <th className="px-4 py-3 text-right">최대 낙폭</th>
                    <th className="px-4 py-3 text-right">Sharpe</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {report.candidateStrategies.map((candidate) => (
                    <tr
                      key={candidate.id}
                      className={candidate.selected ? "bg-blue-50/70" : ""}
                    >
                      <td className="px-4 py-4 align-top">
                        <div className="flex items-center gap-2">
                          <span className="font-semibold text-slate-900">
                            {candidate.name}
                          </span>
                          {candidate.selected && (
                            <Badge tone="blue">최종 선택</Badge>
                          )}
                        </div>
                        <p className="mt-2 max-w-xs text-xs leading-5 text-slate-500">
                          {candidate.evaluation}
                        </p>
                      </td>
                      <td className="px-4 py-4 align-top text-slate-600">
                        {candidate.selectionRule}
                      </td>
                      <td className="px-4 py-4 align-top text-slate-600">
                        {candidate.weightingRule}
                        <span className="mt-1 block text-xs text-slate-400">
                          {candidate.rebalance} 리밸런싱
                        </span>
                      </td>
                      <td className="px-4 py-4 text-right align-top tabular-nums">
                        {format.pct(candidate.cumulativeReturn, true)}
                      </td>
                      <td className="px-4 py-4 text-right align-top tabular-nums">
                        {format.pct(candidate.volatility)}
                      </td>
                      <td className="px-4 py-4 text-right align-top tabular-nums">
                        {format.pct(candidate.mdd)}
                      </td>
                      <td className="px-4 py-4 text-right align-top tabular-nums">
                        {format.sharpe(candidate.sharpe)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
          <div className="mt-9 grid grid-cols-[1fr_280px] gap-8">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[690px] text-left text-sm">
                <thead className="border-y border-slate-200 bg-slate-50 text-xs text-slate-500">
                  <tr>
                    <th className="px-3 py-3">기업</th>
                    <th className="px-3 py-3">종목코드</th>
                    <th className="px-3 py-3 text-right">배분 비중</th>
                    <th className="px-3 py-3 text-right">USD</th>
                    <th className="px-3 py-3 text-right">KRW</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {report.allocation.map((item) => (
                    <tr
                      key={item.ticker}
                      onClick={() => setStock(item.ticker)}
                      tabIndex={0}
                      onKeyDown={(event) =>
                        event.key === "Enter" && setStock(item.ticker)
                      }
                      className="cursor-pointer hover:bg-blue-50 focus:bg-blue-50 focus:outline-none"
                    >
                      <td className="px-3 py-3 font-semibold">
                        {item.company}
                      </td>
                      <td className="px-3 py-3 text-slate-500">
                        {item.ticker}
                      </td>
                      <td className="px-3 py-3 text-right tabular-nums">
                        {format.weight(item.weight)}
                      </td>
                      <td className="px-3 py-3 text-right tabular-nums">
                        {format.usd(item.usd)}
                      </td>
                      <td className="px-3 py-3 text-right tabular-nums">
                        {format.krw(item.krw)}
                      </td>
                    </tr>
                  ))}
                </tbody>
                <tfoot className="border-t-2 border-slate-200 font-bold">
                  <tr>
                    <td className="px-3 py-3" colSpan={2}>
                      합계
                    </td>
                    <td className="px-3 py-3 text-right">100.0%</td>
                    <td className="px-3 py-3 text-right">
                      {format.usd(report.calculation.initialCapitalUsd)}
                    </td>
                    <td className="px-3 py-3 text-right">
                      {format.krw(report.conditions.amountKrw)}
                    </td>
                  </tr>
                </tfoot>
              </table>
            </div>
            <div>
              <ResponsiveContainer width="100%" height={230}>
                <PieChart>
                  <Pie
                    data={report.allocation}
                    dataKey="weight"
                    nameKey="ticker"
                    innerRadius={55}
                    outerRadius={88}
                    paddingAngle={2}
                  >
                    {report.allocation.map((item, index) => (
                      <Cell
                        key={item.ticker}
                        fill={
                          [
                            "#1d4ed8",
                            "#3b82f6",
                            "#60a5fa",
                            "#93c5fd",
                            "#cbd5e1",
                          ][index]
                        }
                      />
                    ))}
                  </Pie>
                  <ChartTooltip formatter={(value) => `${value}%`} />
                </PieChart>
              </ResponsiveContainer>
              <p className="text-center text-xs text-slate-500">
                분석 기준일 {report.calculation.compositionDate}
              </p>
            </div>
          </div>
          <div className="mt-6 flex items-center justify-between rounded-xl bg-slate-50 p-4 text-xs text-slate-600">
            <span>
              계산통화 USD · 표시환율{" "}
              {report.calculation.fxRate.toLocaleString("ko-KR")} KRW/USD (
              {report.calculation.fxDate})
            </span>
            <span>KRW 금액은 분석 기준일 환율로 환산</span>
          </div>
          <details className="mt-5 rounded-xl border border-slate-200 px-5 py-4">
            <summary className="text-sm font-semibold text-slate-800">
              전략 규칙과 재조정 방식
            </summary>
            <dl className="mt-4 grid grid-cols-2 gap-4 text-sm">
              {[
                ["투자 대상", report.strategy.universe],
                [
                  "선정 규칙",
                  `최근 ${report.strategy.lookbackMonths}개월 저변동성 상위 ${report.strategy.selectionCount}종목`,
                ],
                ["배분 방식", "역변동성 배분"],
                ["재조정", "분기 첫 거래일"],
                ["제외 종목", report.strategy.exclusions.join(", ") || "없음"],
                ["운용 가정", report.strategy.assumptions.join(" · ")],
              ].map(([label, value]) => (
                <div key={label}>
                  <dt className="text-xs text-slate-400">{label}</dt>
                  <dd className="mt-1 leading-6 text-slate-700">{value}</dd>
                </div>
              ))}
            </dl>
          </details>
        </section>

        <section
          id="performance"
          className="scroll-mt-20 border-b border-slate-200 py-12"
        >
          <p className="text-xs font-bold tracking-widest text-blue-700">04</p>
          <h2 className="mt-2 text-2xl font-bold tracking-tight text-slate-950">
            과거 성과와 해석
          </h2>
          <div className="mt-7 space-y-5">
            {report.narrative.performanceInterpretation.map((item, index) =>
              prose(item, `performance-${index}`),
            )}
          </div>
          <div className="mt-8 grid grid-cols-6 gap-2">
            <MetricCard
              label="누적 수익률"
              value={format.pct(metrics.cumulativeReturn, true)}
            />
            <MetricCard
              label="연환산 수익률"
              value={
                metrics.cagr == null ? "산출 불가" : format.pct(metrics.cagr)
              }
            />
            <MetricCard
              label="연환산 변동성"
              value={
                metrics.volatility == null
                  ? "산출 불가"
                  : format.pct(metrics.volatility)
              }
            />
            <MetricCard
              label="Sharpe 비율"
              value={format.sharpe(metrics.sharpe)}
            />
            <MetricCard label="최대 낙폭" value={format.pct(metrics.mdd)} />
            <MetricCard
              label="비교지수 대비"
              value={format.pp(
                metrics.cumulativeReturn - metrics.benchmarkReturn,
              )}
            />
          </div>
          <div
            className="mt-8 h-72"
            aria-label="포트폴리오와 비교지수 성과 차트"
          >
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={report.series}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="date" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} />
                <ChartTooltip
                  formatter={(value) => Number(value).toFixed(2)}
                  labelFormatter={(label) => `날짜 ${label}`}
                />
                <Legend />
                <Line
                  dataKey="portfolio"
                  name="포트폴리오"
                  stroke="#1d4ed8"
                  strokeWidth={2.5}
                  dot
                />
                <Line
                  dataKey="benchmark"
                  name="비교지수"
                  stroke="#64748b"
                  strokeDasharray="6 4"
                  dot
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <div className="mt-7">
            <h3 className="text-sm font-bold text-slate-800">과거 낙폭</h3>
            <div className="mt-2 h-40">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={report.series}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                  <XAxis dataKey="date" tick={{ fontSize: 10 }} />
                  <YAxis unit="%" tick={{ fontSize: 10 }} />
                  <ChartTooltip
                    formatter={(value) => `${Number(value).toFixed(2)}%`}
                  />
                  <Area
                    dataKey="drawdown"
                    name="낙폭"
                    stroke="#dc2626"
                    fill="#fee2e2"
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>
          <details className="mt-6 rounded-xl border border-slate-200 px-5 py-4">
            <summary className="text-sm font-semibold text-slate-800">
              차트 데이터 보기
            </summary>
            <div className="mt-4 overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-y border-slate-200 bg-slate-50">
                    {["날짜", "포트폴리오", "비교지수", "낙폭"].map((item) => (
                      <th key={item} className="px-3 py-2 text-left">
                        {item}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {report.series.map((point) => (
                    <tr key={point.date} className="border-b border-slate-100">
                      <td className="px-3 py-2">{point.date}</td>
                      <td className="px-3 py-2">
                        {point.portfolio.toFixed(2)}
                      </td>
                      <td className="px-3 py-2">
                        {point.benchmark.toFixed(2)}
                      </td>
                      <td className="px-3 py-2">
                        {point.drawdown.toFixed(2)}%
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        </section>

        <section
          id="reconsideration"
          className="scroll-mt-20 border-b border-slate-200 py-12"
        >
          <p className="text-xs font-bold tracking-widest text-blue-700">05</p>
          <h2 className="mt-2 text-2xl font-bold tracking-tight text-slate-950">
            판단의 전제와 재검토 조건
          </h2>
          <div className="mt-7 space-y-5">
            {report.narrative.reconsiderationConditions.map((item, index) =>
              prose(item, `reconsideration-${index}`),
            )}
          </div>
        </section>

        <section id="references" className="scroll-mt-20 pt-12">
          <p className="text-xs font-bold tracking-widest text-blue-700">06</p>
          <h2 className="mt-2 text-2xl font-bold tracking-tight text-slate-950">
            참고자료와 분석 조건
          </h2>
          <div className="mt-7 divide-y divide-slate-100 border-y border-slate-200">
            {report.evidence.map((item, index) => (
              <button
                key={item.id}
                onClick={() => setSource(item)}
                className="flex w-full items-start gap-4 py-4 text-left hover:bg-slate-50"
              >
                <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-blue-50 text-xs font-bold text-blue-700">
                  {index + 1}
                </span>
                <span className="flex-1">
                  <span className="block text-sm font-semibold text-slate-800">
                    {item.sourceTitle}
                  </span>
                  <span className="mt-1 block text-xs text-slate-500">
                    {item.provider} · {item.publicationDate || item.marketDate}
                    {item.section ? ` · ${item.section}` : ""}
                  </span>
                </span>
                <span className="text-xs font-semibold text-blue-700">
                  상세 보기
                </span>
              </button>
            ))}
          </div>
          <details className="mt-6 rounded-xl border border-slate-200 px-5 py-4">
            <summary className="text-sm font-semibold text-slate-800">
              계산 조건과 방법론
            </summary>
            <div className="mt-4 grid grid-cols-3 gap-x-8 gap-y-5 text-sm">
              {[
                [
                  "분석기간",
                  `${report.calculation.startDate}~${report.calculation.endDate}`,
                ],
                ["계산통화", report.calculation.currency],
                ["초기자본", format.usd(report.calculation.initialCapitalUsd)],
                [
                  "비교지수",
                  `${report.calculation.benchmark} · ${report.calculation.benchmarkMeaning}`,
                ],
                ["거래비용", `${report.calculation.transactionCostPct}%/거래`],
                [
                  "무위험수익률",
                  `${report.calculation.riskFreeRatePct}% · ${report.calculation.riskFreeSource}`,
                ],
                ["리밸런싱", "분기 첫 거래일, 전일 신호 사용"],
                [
                  "표시환율",
                  `${report.calculation.fxRate.toLocaleString("ko-KR")}원 · ${report.calculation.fxDate}`,
                ],
                ["구성 기준일", report.calculation.compositionDate],
              ].map(([label, value]) => (
                <div key={label}>
                  <p className="text-xs text-slate-400">{label}</p>
                  <p className="mt-1 leading-6 text-slate-700">{value}</p>
                </div>
              ))}
            </div>
          </details>
          <details className="mt-3 rounded-xl border border-slate-200 px-5 py-4">
            <summary className="text-sm font-semibold text-slate-800">
              분석 범위와 한계
            </summary>
            <ul className="mt-4 space-y-2 text-sm leading-6 text-slate-600">
              {[...report.exclusions, ...report.limitations].map((item) => (
                <li key={item}>• {item}</li>
              ))}
            </ul>
            <p className="mt-4 text-xs leading-5 text-slate-500">
              과거 성과는 실제 투자성과가 아니며 미래 수익을 보장하지 않습니다.
            </p>
          </details>
          <div
            id="analysis-log"
            className="mt-6 flex scroll-mt-20 items-center justify-between rounded-xl bg-slate-50 p-5"
          >
            <div>
              <h3 className="text-sm font-bold text-slate-800">분석Log</h3>
              <p className="mt-1 text-xs text-slate-500">
                {report.execution.length}개 단계 완료 · 마지막 확인{" "}
                {report.createdAt}
              </p>
            </div>
            <Button variant="secondary" onClick={() => setLogs(true)}>
              <ListChecks className="size-4" />
              분석Log 보기
            </Button>
          </div>
        </section>
      </article>

      <div className="flex justify-between border-t border-slate-200 pt-5">
        <Button variant="ghost" onClick={() => navigate({ page: "reports" })}>
          <ArrowLeft className="size-4" />
          리포트 목록
        </Button>
        {fresh ? (
          <Button onClick={startTracking}>이 전략으로 모의투자 시작</Button>
        ) : (
          <Button onClick={reanalyze}>같은 조건으로 재분석</Button>
        )}
      </div>
      {selected && (
        <SecurityPanel
          item={selected}
          evidence={report.evidence.find(
            (item) => item.id === selected.evidenceId,
          )}
          close={() => setStock(null)}
          openSource={(item) => setSource(item)}
        />
      )}
      {source && <SourcePanel item={source} close={() => setSource(null)} />}
      {logs && (
        <ExecutionPanel
          records={report.execution}
          evidence={report.evidence}
          close={() => setLogs(false)}
        />
      )}
    </div>
  )
}

function SidePanel({
  title,
  close,
  children,
}: {
  title: string
  close: () => void
  children: React.ReactNode
}) {
  const closeRef = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    closeRef.current?.focus()
    const handler = (event: KeyboardEvent) => event.key === "Escape" && close()
    window.addEventListener("keydown", handler)
    return () => window.removeEventListener("keydown", handler)
  }, [close])
  return (
    <div
      className="fixed inset-0 z-50 flex"
      role="dialog"
      aria-modal="true"
      aria-label={title}
    >
      <button
        aria-label="패널 닫기"
        className="flex-1 bg-slate-950/30"
        onClick={close}
      />
      <aside className="h-full w-[620px] overflow-y-auto bg-white shadow-2xl">
        <header className="sticky top-0 flex items-center justify-between border-b border-slate-200 bg-white px-6 py-5">
          <h2 className="font-bold text-slate-950">{title}</h2>
          <button
            ref={closeRef}
            aria-label="닫기"
            onClick={close}
            className="rounded-lg p-2 hover:bg-slate-100"
          >
            <X className="size-5" />
          </button>
        </header>
        <div className="p-6">{children}</div>
      </aside>
    </div>
  )
}

function SecurityPanel({
  item,
  evidence,
  close,
  openSource,
}: {
  item: Report["allocation"][number]
  evidence?: Evidence
  close: () => void
  openSource: (item: Evidence) => void
}) {
  return (
    <SidePanel title={`${item.company} · ${item.ticker}`} close={close}>
      <div className="grid grid-cols-2 gap-3">
        <MetricCard label="배정 비중" value={format.weight(item.weight)} />
        <MetricCard
          label="배정 금액"
          value={format.usd(item.usd)}
          note={format.krw(item.krw)}
        />
      </div>
      <div className="mt-6 space-y-5">
        {[
          ["선택 이유", item.selectionReason],
          ["비중 배정 이유", item.weightingReason],
          ["포트폴리오 역할", item.role],
          [
            "적용 비중 한도",
            `${format.weight(item.capPct)}${
              item.capAdjusted ? " · 한도 조정 적용" : ""
            }`,
          ],
          ["관련 위험", item.risk],
        ].map(([title, text]) => (
          <div key={title}>
            <h3 className="text-sm font-bold text-slate-800">{title}</h3>
            <p className="mt-2 text-sm leading-6 text-slate-600">{text}</p>
          </div>
        ))}
      </div>
      {evidence && (
        <button
          onClick={() => openSource(evidence)}
          className="mt-6 flex w-full items-center justify-between rounded-xl border border-blue-200 bg-blue-50 p-4 text-left"
        >
          <span>
            <span className="block text-xs font-bold text-blue-600">
              관련 자료
            </span>
            <span className="mt-1 block text-sm font-semibold text-blue-950">
              {evidence.value}
            </span>
          </span>
          <ChevronRight className="size-5 text-blue-700" />
        </button>
      )}
    </SidePanel>
  )
}

function SourcePanel({ item, close }: { item: Evidence close: () => void }) {
  return (
    <SidePanel title="참고자료 상세" close={close}>
      <dl className="space-y-5">
        {[
          ["문서 제목", item.sourceTitle],
          ["발행기관", item.provider],
          ["발행일", item.publicationDate || item.marketDate || "기록 없음"],
          ["관련 부분", item.section || "관련 항목 전체"],
          ["자료 내용", item.excerpt || item.value],
          ["뒷받침하는 판단", item.supportedClaim || item.usedFor],
          ["분석에 사용한 값", item.value],
          ["자료 수집시각", item.collectedAt],
          ["데이터베이스 기록번호", item.recordId || item.id],
          ["원문", item.sourceUrl || "등록된 원문 링크 없음"],
        ].map(([key, value]) => (
          <div key={key}>
            <dt className="text-xs font-semibold text-slate-400">{key}</dt>
            <dd className="mt-1 text-sm leading-6 text-slate-700">{value}</dd>
          </div>
        ))}
      </dl>
      {item.marketDate && (
        <p className="mt-6 rounded-xl bg-slate-50 p-4 text-xs leading-5 text-slate-600">
          가격 기반 지표는 이 자료와 리포트의 분석기간, 거래비용, 재조정 조건을
          함께 적용해 계산했습니다.
        </p>
      )}
    </SidePanel>
  )
}

function ExecutionPanel({
  records,
  evidence,
  close,
}: {
  records: ExecutionRecord[]
  evidence: Evidence[]
  close: () => void
}) {
  return (
    <SidePanel title="분석Log" close={close}>
      <div className="space-y-4">
        {records.map((item, index) => (
          <details
            key={item.id}
            className="rounded-xl border border-slate-200 p-4"
            open
          >
            <summary className="cursor-pointer list-none">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-[11px] font-bold text-slate-400">
                    {String(index + 1).padStart(2, "0")} ·{" "}
                    {item.startedAt || "시각 기록 없음"}
                  </p>
                  <p className="mt-1 font-bold text-slate-800">{item.stage}</p>
                </div>
                <Badge
                  tone={
                    item.status === "completed"
                      ? "green"
                      : item.status === "partial"
                        ? "amber"
                        : "red"
                  }
                >
                  {item.status === "completed"
                    ? "완료"
                    : item.status === "partial"
                      ? "일부 완료"
                      : "실패"}
                </Badge>
              </div>
              <p className="mt-2 text-sm text-slate-600">{item.summary}</p>
            </summary>
            <div className="mt-4 space-y-4 border-t border-slate-100 pt-4 text-xs leading-5 text-slate-500">
              <p>
                시작: {item.startedAt || "기록 없음"} · 종료:{" "}
                {item.endedAt || "기록 없음"}
              </p>
              <div>
                <p className="font-bold text-slate-600">참조한 DB 자료</p>
                {item.sources.length > 0 ? (
                  <ul className="mt-1 space-y-1">
                    {item.sources.map((sourceId) => {
                      const source = evidence.find(
                        (record) => record.id === sourceId,
                      )
                      return (
                        <li key={sourceId}>
                          {source
                            ? `${source.sourceTitle} · ${source.recordId || source.id}`
                            : sourceId}
                        </li>
                      )
                    })}
                  </ul>
                ) : (
                  <p className="mt-1">참조 자료 없음</p>
                )}
              </div>
              <div>
                <p className="font-bold text-slate-600">호출한 Tool</p>
                <p className="mt-1">
                  {item.tools?.join(" · ") || "호출 기록 없음"}
                </p>
              </div>
              <div>
                <p className="font-bold text-slate-600">LLM 출력</p>
                <p className="mt-1 whitespace-pre-wrap text-slate-700">
                  {item.modelOutput || item.summary}
                </p>
              </div>
              <div>
                <p className="font-bold text-slate-600">판단 요약</p>
                <p className="mt-1 whitespace-pre-wrap text-slate-700">
                  {item.decisionSummary || item.summary}
                </p>
              </div>
              {item.issues.length > 0 && (
                <div>
                  <p className="font-bold text-slate-600">제외·오류</p>
                  <p className="mt-1">{item.issues.join(" · ")}</p>
                </div>
              )}
              {item.technical && (
                <p className="font-mono">기술 식별자: {item.technical}</p>
              )}
            </div>
          </details>
        ))}
      </div>
    </SidePanel>
  )
}

function Dialog({
  title,
  close,
  children,
}: {
  title: string
  close: () => void
  children: React.ReactNode
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-8"
      role="dialog"
      aria-modal="true"
      aria-label={title}
    >
      <button
        aria-label="대화상자 닫기"
        className="absolute inset-0 bg-slate-950/40"
        onClick={close}
      />
      <div className="relative max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-2xl bg-white shadow-2xl">
        <header className="flex items-center justify-between border-b border-slate-200 px-6 py-5">
          <h2 className="font-bold text-slate-950">{title}</h2>
          <IconButton label="닫기" onClick={close}>
            <X className="size-5" />
          </IconButton>
        </header>
        {children}
      </div>
    </div>
  )
}

function TrackingDialog({
  report,
  close,
  confirm,
}: {
  report: Report
  close: () => void
  confirm: (fail: boolean) => void
}) {
  return (
    <Dialog title="모의투자 시작 확인" close={close}>
      <div className="space-y-5 p-6">
        <Alert title="모의투자 안내" tone="info">
          실제 매매 또는 주문은 발생하지 않습니다. 앱이 닫혀 있는 동안 자동
          업데이트되지 않습니다.
        </Alert>
        <div>
          <p className="text-xs font-bold text-slate-400">전략명</p>
          <p className="mt-1 font-bold text-slate-900">{report.title}</p>
        </div>
        <div className="grid grid-cols-2 gap-3">
          {[
            ["가상 초기자본", format.krw(report.conditions.amountKrw)],
            ["추적 시작", `${APP_CONFIG.canonicalAsOf} 장 마감 후`],
            ["시작가격 기준", "분석 기준일 종가"],
            ["비교지수", report.calculation.benchmark],
            ["업데이트", "앱 실행 시 최신 자료 확인"],
            ["리밸런싱", report.strategy.rebalance],
          ].map(([label, value]) => (
            <div key={label} className="rounded-xl bg-slate-50 p-3">
              <p className="text-[11px] text-slate-400">{label}</p>
              <p className="mt-1 text-sm font-semibold">{value}</p>
            </div>
          ))}
        </div>
        <div>
          <p className="text-sm font-bold text-slate-800">시작 구성</p>
          <div className="mt-2 grid grid-cols-2 gap-2">
            {report.allocation.map((item) => (
              <div
                key={item.ticker}
                className="flex justify-between rounded-lg border border-slate-200 px-3 py-2 text-sm"
              >
                <span>
                  {item.company} ({item.ticker})
                </span>
                <b>{format.weight(item.weight)}</b>
              </div>
            ))}
          </div>
        </div>
      </div>
      <footer className="flex justify-end gap-2 border-t border-slate-200 px-6 py-4">
        <Button variant="ghost" onClick={close}>
          취소
        </Button>
        <Button onClick={() => confirm(false)}>모의투자 시작</Button>
      </footer>
    </Dialog>
  )
}

function PaperList({
  papers,
  navigate,
}: {
  papers: PaperPortfolio[]
  navigate: (route: Route) => void
}) {
  const [mode, setMode] = useState<"ready" | "loading" | "error">("ready")
  if (mode === "loading")
    return <div className="h-64 animate-pulse rounded-2xl bg-slate-200" />
  if (mode === "error")
    return (
      <EmptyState
        title="모의투자 데이터를 불러오지 못했습니다."
        description="잠시 후 다시 시도해주세요."
        action={<Button onClick={() => setMode("ready")}>다시 시도</Button>}
      />
    )
  return (
    <div className="space-y-7">
      <PageHeader
        eyebrow="모의투자"
        title="추적 중인 전략"
        description="전략별 가상 투자금의 변화와 같은 기간 비교지수 성과를 확인합니다."
      />
      {papers.length === 0 ? (
        <EmptyState
          title="추적 중인 전략이 없습니다."
          description="새 분석을 완료한 뒤 리포트에서 모의투자 시작을 확인해주세요."
          action={
            <Button onClick={() => navigate({ page: "home" })}>
              새 분석 시작
            </Button>
          }
        />
      ) : (
        <div className="space-y-3">
          {papers.map((paper) => {
            const ret =
              (paper.currentValueKrw / paper.initialCapitalKrw - 1) * 100
            return (
              <Card key={paper.id} className="p-5">
                <div className="flex items-center gap-6">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <h2 className="font-bold text-slate-900">
                        {paper.title}
                      </h2>
                      <Badge
                        tone={
                          paper.updateStatus === "정상"
                            ? "green"
                            : paper.updateStatus === "업데이트 지연"
                              ? "amber"
                              : "red"
                        }
                      >
                        {paper.updateStatus}
                      </Badge>
                    </div>
                    <div className="mt-4 grid grid-cols-6 gap-4 text-xs">
                      <div>
                        <p className="text-slate-400">시작일</p>
                        <p className="mt-1 font-semibold">{paper.startedAt}</p>
                      </div>
                      <div>
                        <p className="text-slate-400">최신 기준</p>
                        <p className="mt-1 font-semibold">{paper.latestAsOf}</p>
                      </div>
                      <div>
                        <p className="text-slate-400">가상 초기자본</p>
                        <p className="mt-1 font-semibold">
                          {format.krw(paper.initialCapitalKrw)}
                        </p>
                      </div>
                      <div>
                        <p className="text-slate-400">가상 현재가치</p>
                        <p className="mt-1 font-semibold">
                          {format.krw(paper.currentValueKrw)}
                        </p>
                      </div>
                      <div>
                        <p className="text-slate-400">시작 후 수익률</p>
                        <p className="mt-1 font-semibold text-blue-700">
                          {format.pct(ret, true)}
                        </p>
                      </div>
                      <div>
                        <p className="text-slate-400">비교지수 / 차이</p>
                        <p className="mt-1 font-semibold">
                          {format.pct(paper.benchmarkReturn, true)} ·{" "}
                          {format.pp(ret - paper.benchmarkReturn)}
                        </p>
                      </div>
                    </div>
                  </div>
                  <Button
                    variant="secondary"
                    onClick={() =>
                      navigate({ page: "paper-detail", id: paper.id })
                    }
                  >
                    상세 보기
                  </Button>
                </div>
              </Card>
            )
          })}
        </div>
      )}
      <p className="text-center text-xs text-slate-500">
        모의투자 자료는 앱을 실행해 확인할 때 갱신됩니다.
      </p>
    </div>
  )
}

function PaperDetail({
  paper,
  report,
  navigate,
  reanalyze,
}: {
  paper: PaperPortfolio
  report: Report
  navigate: (route: Route) => void
  reanalyze: () => void
}) {
  const [view, setView] = useState<"tracking" | "backtest">("tracking")
  const ret = (paper.currentValueKrw / paper.initialCapitalKrw - 1) * 100
  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="모의투자 상세"
        title={paper.title}
        description={`추적 시작 ${paper.startedAt} · 최신 데이터 ${paper.latestAsOf}`}
        actions={<Button onClick={reanalyze}>이 전략을 바탕으로 재분석</Button>}
      />
      <Alert title="가상 성과" tone="info">
        실제 투자금이나 주문이 아닙니다. 추적 이후 성과와 생성 전 과거
        백테스트를 하나의 연속 곡선으로 연결하지 않습니다.
      </Alert>
      <div className="inline-flex rounded-xl border border-slate-200 bg-white p-1">
        <button
          onClick={() => setView("tracking")}
          className={`rounded-lg px-4 py-2 text-sm font-semibold ${
            view === "tracking" ? "bg-blue-700 text-white" : "text-slate-600"
          }`}
        >
          추적 시작 이후 성과
        </button>
        <button
          onClick={() => setView("backtest")}
          className={`rounded-lg px-4 py-2 text-sm font-semibold ${
            view === "backtest" ? "bg-blue-700 text-white" : "text-slate-600"
          }`}
        >
          과거 백테스트
        </button>
      </div>
      {view === "tracking" ? (
        <>
          <div className="grid grid-cols-5 gap-3">
            <MetricCard
              label="가상 초기자본"
              value={format.krw(paper.initialCapitalKrw)}
            />
            <MetricCard
              label="가상 현재가치"
              value={format.krw(paper.currentValueKrw)}
            />
            <MetricCard
              label="가상 손익"
              value={format.krw(
                paper.currentValueKrw - paper.initialCapitalKrw,
              )}
            />
            <MetricCard label="시작 후 수익률" value={format.pct(ret, true)} />
            <MetricCard
              label="비교지수 차이"
              value={format.pp(ret - paper.benchmarkReturn)}
            />
          </div>
          <Card className="p-6">
            <h2 className="font-bold text-slate-900">추적 시작 이후 성과</h2>
            <p className="mt-1 text-xs text-slate-500">
              {paper.startedAt}~{paper.latestAsOf} · KRW 가상 가치 · 같은 기간
              benchmark
            </p>
            <div className="mt-5 h-64">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={paper.series}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                  <XAxis dataKey="date" />
                  <YAxis
                    tickFormatter={(value) =>
                      `${Math.round(value / 1_000_000)}백만`
                    }
                  />
                  <ChartTooltip
                    formatter={(value) => format.krw(Number(value))}
                  />
                  <Legend />
                  <Line
                    dataKey="portfolio"
                    name="모의 포트폴리오"
                    stroke="#1d4ed8"
                    strokeWidth={2}
                  />
                  <Line
                    dataKey="benchmark"
                    name="동일 기간 비교지수"
                    stroke="#64748b"
                    strokeDasharray="6 4"
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </Card>
          <Card className="p-6">
            <h2 className="font-bold text-slate-900">종목별 현재 상태</h2>
            <div className="mt-4 overflow-x-auto">
              <table className="w-full min-w-[800px] text-sm">
                <thead className="border-y border-slate-200 bg-slate-50 text-xs text-slate-500">
                  <tr>
                    {[
                      "종목",
                      "시작 비중",
                      "현재 비중",
                      "전략 목표",
                      "최근 리밸런싱 적용",
                      "현재 가상가치",
                    ].map((item) => (
                      <th key={item} className="px-3 py-3 text-left">
                        {item}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {paper.holdings.map((item) => (
                    <tr key={item.ticker} className="border-b border-slate-100">
                      <td className="px-3 py-3 font-semibold">
                        {item.company} ({item.ticker})
                      </td>
                      <td className="px-3 py-3">
                        {format.weight(item.initialWeight)}
                      </td>
                      <td className="px-3 py-3">
                        {format.weight(item.currentWeight)}
                      </td>
                      <td className="px-3 py-3">
                        {format.weight(item.targetWeight)}
                      </td>
                      <td className="px-3 py-3">
                        {format.weight(item.lastRebalanceWeight)}
                      </td>
                      <td className="px-3 py-3">
                        {format.krw(item.currentValueKrw)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
          <Card className="p-6">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="font-bold text-slate-900">
                  원래 아이디어와 적용 규칙
                </h2>
                <p className="mt-2 text-sm text-slate-600">{report.idea}</p>
              </div>
              <Button
                variant="secondary"
                onClick={() => navigate({ page: "report", id: report.id })}
              >
                원본 리포트 보기
              </Button>
            </div>
            <p className="mt-4 text-sm text-slate-600">{report.summary}</p>
            <div className="mt-4 space-y-2">
              {paper.rebalanceRecords.map((item) => (
                <div
                  key={item.date}
                  className="rounded-xl bg-slate-50 p-3 text-sm"
                >
                  <b>{item.date}</b>
                  <span className="ml-3 text-slate-600">{item.summary}</span>
                </div>
              ))}
            </div>
          </Card>
        </>
      ) : (
        <Card className="p-6">
          <h2 className="font-bold text-slate-900">과거 백테스트</h2>
          <p className="mt-1 text-xs text-slate-500">
            {report.calculation.startDate}~{report.calculation.endDate} · 전략
            전략 생성 이전 분석기간
          </p>
          <div className="mt-5 grid grid-cols-4 gap-3">
            <MetricCard
              label="누적 수익률"
              value={format.pct(report.metrics.cumulativeReturn, true)}
            />
            <MetricCard
              label="CAGR"
              value={
                report.metrics.cagr == null
                  ? "산출 불가"
                  : format.pct(report.metrics.cagr)
              }
            />
            <MetricCard
              label="변동성"
              value={
                report.metrics.volatility == null
                  ? "산출 불가"
                  : format.pct(report.metrics.volatility)
              }
            />
            <MetricCard
              label="MDD"
              value={format.pct(report.metrics.mdd)}
              danger
            />
          </div>
        </Card>
      )}
    </div>
  )
}

function RevisionPanel({
  report,
  close,
  confirm,
}: {
  report: Report
  close: () => void
  confirm: (idea: string, cap: number) => void
}) {
  const [idea, setIdea] = useState("")
  const [cap, setCap] = useState(report.conditions.globalCapPct)
  const [reviewed, setReviewed] = useState(false)
  return (
    <SidePanel title="전략 수정" close={close}>
      <Badge tone="slate">참조 리포트</Badge>
      <h3 className="mt-2 font-bold text-slate-900">{report.title}</h3>
      <p className="mt-2 text-sm leading-6 text-slate-600">{report.summary}</p>
      <div className="mt-6 space-y-5">
        <Field label="자연어 수정 요청">
          <textarea
            className={`${inputClass} min-h-28`}
            value={idea}
            onChange={(event) => {
              setIdea(event.target.value)
              setReviewed(false)
            }}
            placeholder="예: 산업 집중을 줄이고 종목당 최대 비중을 20%로 낮춰줘."
          />
        </Field>
        <Field label="관련 조건: 종목당 최대 비중">
          <div className="relative">
            <input
              className={`${inputClass} pr-8`}
              type="number"
              value={cap}
              onChange={(event) => {
                setCap(Number(event.target.value))
                setReviewed(false)
              }}
            />
            <span className="absolute right-3 top-2.5 text-sm text-slate-500">
              %
            </span>
          </div>
        </Field>
        <div className="rounded-xl border border-slate-200 p-4">
          <p className="text-xs font-bold text-slate-400">원본 → 제안</p>
          <p className="mt-2 text-sm text-slate-700">
            공통 한도 {report.conditions.globalCapPct}% →{" "}
            <b className="text-blue-700">{cap}%</b>
          </p>
        </div>
        <Alert title="기본 투자조건은 변경되지 않습니다." tone="info">
          수정안은 새 분석과 새 리포트로 저장됩니다. 원본 리포트와 기존
          모의투자는 유지됩니다.
        </Alert>
        <Button
          variant="secondary"
          className="w-full"
          onClick={() => setReviewed(true)}
        >
          변경 조건 확인
        </Button>
        {reviewed && (
          <Alert title="변경 조건 확인 완료" tone="success">
            이제 같은 확인·검증·분석 흐름으로 수정안을 분석할 수 있습니다.
          </Alert>
        )}
        <Button
          className="w-full"
          disabled={!reviewed || !idea.trim()}
          onClick={() => confirm(idea, cap)}
        >
          수정안 분석하기
        </Button>
      </div>
    </SidePanel>
  )
}

function ComparisonScreen({
  revised,
  original,
  navigate,
  startTracking,
}: {
  revised: Report
  original: Report
  navigate: (route: Route) => void
  startTracking: () => void
}) {
  const rows = [
    [
      "종목당 한도",
      `${original.conditions.globalCapPct}%`,
      `${revised.conditions.globalCapPct}%`,
    ],
    ["선택 규칙", "최저 변동성 상위 N개", "최저 변동성 상위 N개"],
    ["가중 규칙", "역변동성", "역변동성"],
    ["리밸런싱", original.strategy.rebalance, revised.strategy.rebalance],
    [
      "누적 수익률",
      format.pct(original.metrics.cumulativeReturn, true),
      format.pct(revised.metrics.cumulativeReturn, true),
    ],
    [
      "연환산 변동성",
      format.pct(original.metrics.volatility ?? 0),
      format.pct(revised.metrics.volatility ?? 0),
    ],
    ["MDD", format.pct(original.metrics.mdd), format.pct(revised.metrics.mdd)],
  ]
  return (
    <div className="space-y-7">
      <PageHeader
        eyebrow="수정안 비교"
        title="원본과 수정안을 같은 조건으로 비교했습니다."
        description="한 지표가 좋아졌다고 수정안이 보편적으로 더 낫다고 판단하지 않습니다."
        actions={
          <Button onClick={startTracking}>수정안으로 모의투자 시작</Button>
        }
      />
      <Alert title="동일 비교 조건" tone="info">
        {original.calculation.startDate}~{original.calculation.endDate}, 같은
        비교지표·거래비용·USD 계산 조건을 사용했습니다.
      </Alert>
      <Card className="overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-50">
            <tr>
              <th className="px-5 py-4 text-left">비교 항목</th>
              <th className="px-5 py-4 text-left">원본</th>
              <th className="px-5 py-4 text-left">수정안</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {rows.map(([label, before, after]) => (
              <tr key={label}>
                <td className="px-5 py-4 font-semibold">{label}</td>
                <td className="px-5 py-4 text-slate-600">{before}</td>
                <td className="px-5 py-4 font-semibold text-blue-700">
                  {after}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
      <div className="grid grid-cols-2 gap-5">
        <Card className="p-6">
          <h2 className="font-bold text-slate-900">개선 가능성</h2>
          <p className="mt-3 text-sm leading-6 text-slate-600">
            종목당 한도를 낮추면 개별 종목 충격이 포트폴리오에 미치는 영향이
            줄어들 수 있습니다. 과거 분석에서는 최대 낙폭이 소폭 낮아졌습니다.
          </p>
        </Card>
        <Card className="p-6">
          <h2 className="font-bold text-slate-900">불리한 상충관계</h2>
          <p className="mt-3 text-sm leading-6 text-slate-600">
            상승 기여가 큰 종목의 비중도 제한되어 누적 수익률이 낮아질 수
            있습니다. 더 많은 종목이 필요해져 데이터 결측 위험도 커집니다.
          </p>
        </Card>
      </div>
      <div className="flex justify-between">
        <Button
          variant="ghost"
          onClick={() => navigate({ page: "report", id: original.id })}
        >
          원본 리포트
        </Button>
        <Button
          variant="secondary"
          onClick={() => navigate({ page: "report", id: revised.id })}
        >
          수정안 리포트 보기
        </Button>
      </div>
    </div>
  )
}

export default function App() {
  const [route, setRoute] = useState<Route>(parseRoute)
  const [data, setData] = useState<AppData | null>(null)
  const [loadError, setLoadError] = useState("")
  const [draft, setDraft] = useState<AnalysisDraft | null>(null)
  const [outcome, setOutcome] = useState<DemoOutcome>("success")
  const [freshReportId, setFreshReportId] = useState<string | null>(null)
  const [unsavedReport, setUnsavedReport] = useState<Report | null>(null)
  const [trackingReport, setTrackingReport] = useState<Report | null>(null)
  const [revisionReport, setRevisionReport] = useState<Report | null>(null)

  useEffect(() => {
    try {
      const loaded = localDataService.load()
      setData(loaded)
      if (!loaded.profile && parseRoute().page !== "profile")
        window.location.hash = "#/profile/setup"
    } catch (error) {
      setLoadError(
        error instanceof Error
          ? error.message
          : "저장된 자료를 읽지 못했습니다.",
      )
    }
    const handler = () => setRoute(parseRoute())
    window.addEventListener("hashchange", handler)
    return () => window.removeEventListener("hashchange", handler)
  }, [])

  const navigate = (next: Route) => {
    if (next.page !== "report" && next.page !== "comparison")
      setFreshReportId(null)
    window.location.hash = routePath(next)
    setRoute(next)
    window.scrollTo({ top: 0 })
  }

  const persist = (next: AppData) => {
    localDataService.save(next)
    setData(next)
  }

  const saveProfile = async (profile: Profile, fail: boolean) => {
    if (!data) return false
    if (fail) return false
    try {
      const next = localDataService.saveProfile(data, profile)
      setData(next)
      navigate({ page: "home" })
      return true
    } catch {
      return false
    }
  }

  const startAnalysis = (
    idea: string,
    source?: Report,
    mode: AnalysisDraft["mode"] = "new",
  ) => {
    if (!data?.profile) return
    const conditions = source
      ? structuredClone(source.conditions)
      : defaultConditions(data.profile)
    if (/nvidia|엔비디아|NVDA/i.test(idea) && !/낮|제한|적게/i.test(idea))
      conditions.namedTickers = ["NVDA"]
    setDraft({
      idea,
      conditions,
      answers: [],
      clarificationCount: 0,
      mode,
      sourceReportId: source?.id,
    })
    setOutcome("success")
    navigate({ page: "review" })
  }

  const completeAnalysis = (report: Report, saveFailure: boolean) => {
    if (!data) return
    setFreshReportId(report.id)
    if (saveFailure) {
      report.saved = false
      setUnsavedReport(report)
    } else {
      const next = localDataService.saveReport(data, report)
      setData(next)
    }
    if (report.sourceReportId) navigate({ page: "comparison", id: report.id })
    else navigate({ page: "report", id: report.id })
  }

  const retryReportSave = (report: Report) => {
    if (!data) return
    const saved = { ...report, saved: true }
    const next = localDataService.saveReport(data, saved)
    setData(next)
    setUnsavedReport(null)
  }

  const createPaper = (report: Report) => {
    if (!data) return
    const duplicate = data.paperPortfolios.find(
      (item) => item.reportId === report.id,
    )
    if (duplicate) {
      setTrackingReport(null)
      navigate({ page: "paper-detail", id: duplicate.id })
      return
    }
    const paper: PaperPortfolio = {
      id: `paper-${Date.now()}`,
      reportId: report.id,
      title: report.title,
      isDemo: true,
      startedAt: APP_CONFIG.canonicalAsOf,
      latestAsOf: `${APP_CONFIG.canonicalAsOf} 18:00`,
      initialCapitalKrw: report.conditions.amountKrw,
      currentValueKrw: report.conditions.amountKrw,
      benchmarkReturn: 0,
      updateStatus: "정상",
      series: [
        {
          date: APP_CONFIG.canonicalAsOf,
          portfolio: report.conditions.amountKrw,
          benchmark: report.conditions.amountKrw,
          drawdown: 0,
        },
      ],
      holdings: report.allocation.map((item) => ({
        ticker: item.ticker,
        company: item.company,
        initialWeight: item.weight,
        currentWeight: item.weight,
        targetWeight: item.weight,
        lastRebalanceWeight: item.weight,
        currentValueKrw: item.krw,
      })),
      rebalanceRecords: [
        {
          date: APP_CONFIG.canonicalAsOf,
          summary:
            "추적 시작 목표 비중을 적용했습니다. 실제 주문은 발생하지 않았습니다.",
        },
      ],
    }
    const next = localDataService.savePaper(data, paper)
    setData(next)
    setTrackingReport(null)
    setFreshReportId(null)
    navigate({ page: "paper-detail", id: paper.id })
  }

  if (loadError)
    return (
      <div className="flex min-h-screen min-w-[1180px] items-center justify-center bg-slate-50 p-10">
        <div className="max-w-xl">
          <Alert title="저장된 자료를 불러오지 못했습니다." tone="error">
            {loadError}
            <div className="mt-4 flex gap-2">
              <Button onClick={() => window.location.reload()}>
                다시 시도
              </Button>
              <Button
                variant="danger"
                onClick={() => {
                  const next = localDataService.reset()
                  setData(next)
                  setLoadError("")
                  navigate({ page: "profile", mode: "setup" })
                }}
              >
                저장 데이터 초기화
              </Button>
            </div>
          </Alert>
        </div>
      </div>
    )
  if (!data)
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Loader2 className="size-7 animate-spin text-blue-700" />
        <span className="ml-3 text-sm text-slate-600">
          저장된 자료를 불러오는 중
        </span>
      </div>
    )

  const visibleReport =
    route.page === "report"
      ? data.reports.find((item) => item.id === route.id) ||
        (unsavedReport?.id === route.id ? unsavedReport : undefined)
      : undefined
  const visiblePaper =
    route.page === "paper-detail"
      ? data.paperPortfolios.find((item) => item.id === route.id)
      : undefined
  const sourceForPaper = visiblePaper
    ? data.reports.find((item) => item.id === visiblePaper.reportId)
    : undefined
  const revised =
    route.page === "comparison"
      ? data.reports.find((item) => item.id === route.id) ||
        (unsavedReport?.id === route.id ? unsavedReport : undefined)
      : undefined
  const original = revised?.sourceReportId
    ? data.reports.find((item) => item.id === revised.sourceReportId)
    : undefined

  let content: React.ReactNode
  if (
    route.page === "profile" &&
    (route.mode === "setup" || route.mode === "edit" || !data.profile)
  )
    content = (
      <ProfileWizard
        initial={data.profile || EMPTY_PROFILE}
        setup={!data.profile || route.mode === "setup"}
        onSave={saveProfile}
        onCancel={() =>
          navigate(data.profile ? { page: "profile" } : { page: "home" })
        }
      />
    )
  else if (route.page === "profile" && data.profile)
    content = <ProfileSummary profile={data.profile} navigate={navigate} />
  else if (route.page === "home")
    content = (
      <HomeScreen
        data={data}
        navigate={navigate}
        startAnalysis={startAnalysis}
      />
    )
  else if (route.page === "review" && draft && data.profile)
    content = (
      <ReviewScreen
        profile={data.profile}
        draft={draft}
        setDraft={setDraft}
        run={() => navigate({ page: "run" })}
        navigate={navigate}
      />
    )
  else if (route.page === "run" && draft)
    content = (
      <RunScreen
        draft={draft}
        outcome={outcome}
        onComplete={completeAnalysis}
        onCancel={() => {
          if (data) {
            const next = { ...data, interruptedDraft: draft }
            persist(next)
          }
        }}
        onEdit={() => navigate({ page: "review" })}
      />
    )
  else if (route.page === "reports")
    content = <ReportList reports={data.reports} navigate={navigate} />
  else if (route.page === "report" && visibleReport)
    content = (
      <ReportDetail
        report={visibleReport}
        fresh={freshReportId === visibleReport.id}
        navigate={navigate}
        startTracking={() => setTrackingReport(visibleReport)}
        reanalyze={() =>
          startAnalysis(visibleReport.idea, visibleReport, "reanalyze")
        }
        revise={() => setRevisionReport(visibleReport)}
        retrySave={() => retryReportSave(visibleReport)}
      />
    )
  else if (route.page === "paper")
    content = <PaperList papers={data.paperPortfolios} navigate={navigate} />
  else if (route.page === "paper-detail" && visiblePaper && sourceForPaper)
    content = (
      <PaperDetail
        paper={visiblePaper}
        report={sourceForPaper}
        navigate={navigate}
        reanalyze={() =>
          startAnalysis(sourceForPaper.idea, sourceForPaper, "revision")
        }
      />
    )
  else if (route.page === "comparison" && revised && original)
    content = (
      <ComparisonScreen
        revised={revised}
        original={original}
        navigate={navigate}
        startTracking={() => setTrackingReport(revised)}
      />
    )
  else
    content = (
      <EmptyState
        title="요청한 화면을 찾을 수 없습니다."
        description="기록이 삭제되었거나 불러오는 중 문제가 발생했습니다."
        action={
          <Button onClick={() => navigate({ page: "home" })}>홈으로</Button>
        }
      />
    )

  return (
    <Shell route={route} data={data} navigate={navigate}>
      {data.interruptedDraft && route.page === "home" && (
        <div className="mb-5">
          <Alert title="중단된 분석이 있습니다." tone="warning">
            자동으로 다시 시작하지 않았습니다.
            <div className="mt-3 flex gap-2">
              <Button
                variant="secondary"
                onClick={() => {
                  setDraft(data.interruptedDraft!)
                  navigate({ page: "review" })
                }}
              >
                조건 확인 후 재시도
              </Button>
              <Button
                variant="ghost"
                onClick={() => {
                  const next = { ...data, interruptedDraft: undefined }
                  persist(next)
                }}
              >
                삭제
              </Button>
            </div>
          </Alert>
        </div>
      )}
      {content}
      {trackingReport && (
        <TrackingDialog
          report={trackingReport}
          close={() => setTrackingReport(null)}
          confirm={() => createPaper(trackingReport)}
        />
      )}
      {revisionReport && (
        <RevisionPanel
          report={revisionReport}
          close={() => setRevisionReport(null)}
          confirm={(idea, cap) => {
            const source = revisionReport
            setRevisionReport(null)
            if (!data.profile) return
            const revisedConditions = structuredClone(source.conditions)
            revisedConditions.globalCapPct = cap
            revisedConditions.analysisOverrides = [
              ...new Set([
                ...revisedConditions.analysisOverrides,
                "globalCapPct",
              ]),
            ]
            setDraft({
              idea,
              conditions: revisedConditions,
              answers: [],
              clarificationCount: 0,
              mode: "revision",
              sourceReportId: source.id,
            })
            navigate({ page: "review" })
          }}
        />
      )}
    </Shell>
  )
}
