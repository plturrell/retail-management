export interface ShiftRead {
  id: string;
  schedule_id: string;
  user_id: string;
  shift_date: string; // "YYYY-MM-DD"
  start_time: string; // "HH:MM:SS"
  end_time: string;   // "HH:MM:SS"
  break_minutes: number;
  notes: string | null;
  hours: number;
}

export interface ShiftCreate {
  user_id: string;
  shift_date: string;
  start_time: string;
  end_time: string;
  break_minutes: number;
  notes: string | null;
}

export interface ShiftUpdate {
  user_id?: string;
  shift_date?: string;
  start_time?: string;
  end_time?: string;
  break_minutes?: number;
  notes?: string | null;
}

export interface ScheduleRead {
  id: string;
  store_id: string;
  week_start: string;
  status: "draft" | "published";
  created_by: string;
  published_at: string | null;
  shifts: ShiftRead[];
  created_at: string;
  updated_at: string;
}

export interface ScheduleCreate {
  store_id: string;
  week_start: string; // Must be Monday
}

export interface ScheduleUpdate {
  status: "draft" | "published";
}

export interface WeeklyScheduleResponse {
  schedule: ScheduleRead;
  days: {
    date: string;
    shifts: ShiftRead[];
  }[];
}

export interface TimeEntryRead {
  id: string;
  user_id: string;
  store_id: string;
  clock_in: string;
  clock_out: string | null;
  break_minutes: number;
  notes: string | null;
  status: "pending" | "approved" | "rejected";
  approved_by: string | null;
  hours_worked: number | null;
  created_at: string;
  updated_at: string;
}

export interface TimesheetSummaryEntry {
  user_id: string;
  full_name: string;
  total_hours: number;
  total_days: number;
  entries: TimeEntryRead[];
}

export interface TimesheetSummaryResponse {
  period_start: string;
  period_end: string;
  summaries: TimesheetSummaryEntry[];
}

export interface StoreEmployeeRead {
  id: string;
  role_id: string;
  full_name: string;
  email: string;
  phone: string | null;
  role: string;
}
