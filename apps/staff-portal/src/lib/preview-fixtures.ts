// Preview-only fixtures. Activated by VITE_PREVIEW_AUTH=1.
// Used for design QA without a live backend.

const USER_ID = "preview-user-id";
const STORE_ID = "preview-store-id";

const me = {
  data: {
    id: USER_ID,
    full_name: "Aisha Tan",
    email: "aisha@retailsg.com",
    phone: "+65 9123 4567",
    store_roles: [{ store_id: STORE_ID, role: "associate" }],
  },
};

const profile = {
  data: {
    date_of_birth: "1995-08-12",
    nationality: "citizen",
    basic_salary: 3200,
    hourly_rate: 18.5,
    commission_rate: 4,
    bank_account: "•••• 4928",
    bank_name: "DBS Bank",
    cpf_account_number: "S••••567A",
    start_date: "2023-04-01",
    end_date: null,
    is_active: true,
  },
};

function isoDate(offsetDays: number): string {
  const d = new Date();
  d.setDate(d.getDate() + offsetDays);
  return d.toISOString().slice(0, 10);
}

function startOfWeek(): Date {
  const d = new Date();
  const day = d.getDay();
  const diff = d.getDate() - day + (day === 0 ? -6 : 1);
  d.setDate(diff);
  d.setHours(0, 0, 0, 0);
  return d;
}

function shiftDate(offsetFromMon: number): string {
  const d = startOfWeek();
  d.setDate(d.getDate() + offsetFromMon);
  return d.toISOString().slice(0, 10);
}

const shifts = {
  data: [
    {
      id: "s1",
      schedule_id: "sch1",
      user_id: USER_ID,
      shift_date: shiftDate(0),
      start_time: "10:00:00",
      end_time: "18:00:00",
      break_minutes: 60,
      notes: null,
      hours: 7,
    },
    {
      id: "s2",
      schedule_id: "sch1",
      user_id: USER_ID,
      shift_date: shiftDate(1),
      start_time: "12:00:00",
      end_time: "21:00:00",
      break_minutes: 60,
      notes: "Cover for Marcus",
      hours: 8,
    },
    {
      id: "s3",
      schedule_id: "sch1",
      user_id: USER_ID,
      shift_date: shiftDate(3),
      start_time: "09:00:00",
      end_time: "17:00:00",
      break_minutes: 60,
      notes: null,
      hours: 7,
    },
    {
      id: "s4",
      schedule_id: "sch1",
      user_id: USER_ID,
      shift_date: shiftDate(5),
      start_time: "11:00:00",
      end_time: "19:00:00",
      break_minutes: 45,
      notes: "Inventory day",
      hours: 7.25,
    },
  ],
};

function makeTimeEntry(daysAgo: number, hours: number, status: "approved" | "pending" = "approved") {
  const start = new Date();
  start.setDate(start.getDate() - daysAgo);
  start.setHours(10, 0, 0, 0);
  const end = new Date(start);
  end.setHours(end.getHours() + hours);
  return {
    id: `t${daysAgo}`,
    user_id: USER_ID,
    store_id: STORE_ID,
    clock_in: start.toISOString(),
    clock_out: end.toISOString(),
    break_minutes: 60,
    notes: null,
    status,
    hours_worked: hours - 1,
  };
}

const timesheets = {
  data: [
    makeTimeEntry(1, 8),
    makeTimeEntry(2, 8),
    makeTimeEntry(3, 8, "pending"),
    makeTimeEntry(5, 9),
    makeTimeEntry(6, 7),
    makeTimeEntry(7, 8),
  ],
};

const timesheetStatus = { data: null };

function makePayrollRun(monthsAgo: number) {
  const start = new Date();
  start.setMonth(start.getMonth() - monthsAgo, 1);
  const end = new Date(start.getFullYear(), start.getMonth() + 1, 0);
  const basic = 3200;
  const overtime_hours = monthsAgo === 0 ? 4 : 6;
  const overtime_pay = overtime_hours * 27.75;
  const commission_sales = 12000 + monthsAgo * 1500;
  const commission_amount = commission_sales * 0.04;
  const allowances = 100;
  const deductions = 0;
  const gross = basic + overtime_pay + commission_amount + allowances - deductions;
  const cpf_employee = gross * 0.2;
  const cpf_employer = gross * 0.17;
  const net = gross - cpf_employee;
  return {
    id: `run-${monthsAgo}`,
    store_id: STORE_ID,
    period_start: start.toISOString().slice(0, 10),
    period_end: end.toISOString().slice(0, 10),
    status: "approved",
    total_gross: gross,
    total_net: net,
    payslips: [
      {
        id: `slip-${monthsAgo}`,
        payroll_run_id: `run-${monthsAgo}`,
        user_id: USER_ID,
        basic_salary: basic,
        hours_worked: 168,
        overtime_hours,
        overtime_pay,
        allowances,
        deductions,
        commission_sales,
        commission_amount,
        gross_pay: gross,
        cpf_employee,
        cpf_employer,
        net_pay: net,
        notes: monthsAgo === 0 ? "Includes Q1 sales bonus." : null,
        created_at: end.toISOString(),
      },
    ],
  };
}

const payroll = { data: [0, 1, 2, 3, 4, 5].map(makePayrollRun) };

const commissionRules = {
  data: [
    {
      id: "rule-1",
      name: "Standard Tiered Commission",
      tiers: [
        { min: 0, max: 5000, rate: 0.02 },
        { min: 5000, max: 15000, rate: 0.04 },
        { min: 15000, max: 30000, rate: 0.06 },
        { min: 30000, max: null, rate: 0.08 },
      ],
      is_active: true,
    },
  ],
};

function makePerf(from: string, to: string, mySales: number, totalStaff: number) {
  const others = [22000, 18500, 12000, 9800, 7200];
  const allSales = [mySales, ...others.slice(0, totalStaff - 1)].sort((a, b) => b - a);
  const total = allSales.reduce((t, s) => t + s, 0);
  return {
    generated_at: new Date().toISOString(),
    store_id: STORE_ID,
    period_from: from,
    period_to: to,
    total_store_sales: total,
    staff: allSales.map((sales, i) => ({
      user_id: sales === mySales ? USER_ID : `peer-${i}`,
      full_name: sales === mySales ? "Aisha Tan" : `Peer ${i + 1}`,
      total_sales: sales,
      order_count: Math.floor(sales / 180),
      avg_order_value: 180,
      rank: i + 1,
    })),
  };
}

const aiInsights = {
  user_id: USER_ID,
  full_name: "Aisha Tan",
  summary: {
    total_sales: 19500,
    order_count: 108,
    avg_order_value: 180,
    period_from: isoDate(-30),
    period_to: isoDate(0),
  },
  ai_insights:
    "You ranked #2 this month, with sales up 22% versus last month — driven by stronger weekend conversion. Average order value held steady at $180, suggesting your upsell motion is working without discounting. To break into #1, focus on Tuesday afternoons, where your conversion dips below the store average.",
};

export function previewMatch(path: string, _method: string): unknown | undefined {
  // Strip query string for matching
  const [pathname, query] = path.split("?");

  if (pathname === "/users/me") return me;
  if (pathname === `/employees/${USER_ID}/profile`) return profile;
  if (pathname === `/stores/${STORE_ID}/payroll`) return payroll;
  if (pathname === `/stores/${STORE_ID}/commission-rules`) return commissionRules;
  if (pathname === `/stores/${STORE_ID}/schedules/my-shifts`) return shifts;
  if (pathname === "/timesheets/status") return timesheetStatus;
  if (pathname.startsWith(`/stores/${STORE_ID}/timesheets`)) return timesheets;
  if (pathname === "/timesheets/clock-in") {
    return {
      data: {
        ...makeTimeEntry(0, 0, "pending"),
        clock_in: new Date().toISOString(),
        clock_out: null,
        hours_worked: null,
      },
    };
  }
  if (pathname === "/timesheets/clock-out") return { data: makeTimeEntry(0, 1) };
  if (pathname === `/stores/${STORE_ID}/analytics/staff-performance`) {
    const params = new URLSearchParams(query ?? "");
    const from = params.get("from") ?? isoDate(-30);
    const to = params.get("to") ?? isoDate(0);
    // Vary mySales by date to give the trend chart shape
    const seed = (from.charCodeAt(5) + from.charCodeAt(6)) % 9;
    const mySales = 9000 + seed * 1800;
    return makePerf(from, to, mySales, 5);
  }
  if (pathname === `/stores/${STORE_ID}/analytics/staff/${USER_ID}/insights`) return aiInsights;

  return undefined;
}
