"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { getCurrentUser } from "@/lib/auth-client";
import {
  type PlatformSettings,
  type Plan,
  type TenantSummary,
  changeTenantPlan,
  getPlatformSettings,
  listAllTenants,
  listPlans,
  setScrapingPaused,
} from "@/lib/admin-client";

// The platform-operator area — gated by is_superadmin, not by any tenant membership. Lives on
// the root domain (rescope.localhost/admin), never under a tenant subdomain.
export default function AdminPage() {
  const router = useRouter();
  const [authorized, setAuthorized] = useState<boolean | null>(null);
  const [tenants, setTenants] = useState<TenantSummary[] | null>(null);
  const [plans, setPlans] = useState<Plan[]>([]);
  const [settings, setSettings] = useState<PlatformSettings | null>(null);
  const [toggling, setToggling] = useState(false);

  useEffect(() => {
    getCurrentUser().then((user) => {
      if (!user) {
        router.replace("/login");
        return;
      }
      if (!user.is_superadmin) {
        setAuthorized(false);
        return;
      }
      setAuthorized(true);
      Promise.all([listAllTenants(), listPlans(), getPlatformSettings()]).then(
        ([tenantList, planList, settingsRow]) => {
          setTenants(tenantList);
          setPlans(planList);
          setSettings(settingsRow);
        },
      );
    });
  }, [router]);

  async function onChangePlan(tenantId: string, planId: string) {
    const updated = await changeTenantPlan(tenantId, planId);
    setTenants((prev) => (prev ? prev.map((t) => (t.id === tenantId ? updated : t)) : prev));
  }

  async function onToggleKillswitch() {
    if (!settings) return;
    setToggling(true);
    try {
      setSettings(await setScrapingPaused(!settings.scraping_paused));
    } finally {
      setToggling(false);
    }
  }

  if (authorized === null) return null;
  if (authorized === false) {
    return (
      <main className="mx-auto max-w-lg px-6 py-16 text-center">
        <h1 className="text-xl font-semibold">Not authorized</h1>
        <p className="mt-2 text-zinc-600">This area is for platform administrators only.</p>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-4xl px-6 py-10">
      <h1 className="text-2xl font-semibold">Platform admin</h1>

      {settings && (
        <div className="mt-6 flex items-center justify-between rounded-lg border border-zinc-200 bg-white px-4 py-3">
          <div>
            <div className="font-medium">Scraping killswitch</div>
            <p className="text-sm text-zinc-500">
              {settings.scraping_paused
                ? "Paused — no tenant can start or continue a scrape right now."
                : "Running normally."}
            </p>
          </div>
          <button
            onClick={onToggleKillswitch}
            disabled={toggling}
            className={`rounded-md px-4 py-2 text-sm font-medium text-white disabled:opacity-50 ${
              settings.scraping_paused ? "bg-emerald-600" : "bg-red-600"
            }`}
          >
            {settings.scraping_paused ? "Resume scraping" : "Pause scraping"}
          </button>
        </div>
      )}

      <h2 className="mt-8 text-lg font-semibold">Tenants</h2>
      {tenants === null ? null : (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[640px] border-collapse text-left text-sm">
            <thead>
              <tr className="border-b border-zinc-200 text-zinc-500">
                <th className="py-2 pr-4 font-medium">Name</th>
                <th className="py-2 pr-4 font-medium">Members</th>
                <th className="py-2 pr-4 font-medium">Plan</th>
                <th className="py-2 pr-4 font-medium">Spend this month</th>
              </tr>
            </thead>
            <tbody>
              {tenants.map((t) => (
                <tr key={t.id} className="border-b border-zinc-100">
                  <td className="py-2 pr-4">
                    <div className="font-medium">{t.name}</div>
                    <div className="text-xs text-zinc-400">{t.slug}</div>
                  </td>
                  <td className="py-2 pr-4">{t.member_count}</td>
                  <td className="py-2 pr-4">
                    <select
                      value={t.plan_id}
                      onChange={(e) => onChangePlan(t.id, e.target.value)}
                      className="rounded border border-zinc-300 px-2 py-1"
                    >
                      {plans.map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.name}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="py-2 pr-4">${t.spend_this_month_usd.toFixed(4)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}
