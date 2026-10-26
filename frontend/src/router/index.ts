import { createRouter, createWebHistory, type RouteRecordRaw } from "vue-router";
import { useStationAuth } from "@/stores/stationAuth";
import { useAuth } from "@/stores/auth";

const routes: RouteRecordRaw[] = [
  { path: "/login", name: "station-login", component: () => import("@/pages/StationLogin.vue"), meta: { title: "Station sign in" } },
  {
    path: "/",
    name: "print",
    component: () => import("@/pages/PrintPanel.vue"),
    meta: { title: "Print" },
  },
  {
    path: "/admin/login",
    name: "admin-login",
    component: () => import("@/pages/AdminLogin.vue"),
    meta: { title: "Admin login" },
  },
  {
    path: "/admin",
    name: "admin",
    component: () => import("@/pages/Admin.vue"),
    meta: { title: "Admin", requiresAdmin: true },
  },
  {
    path: "/kiosk",
    name: "kiosk",
    component: () => import("@/pages/KioskPanel.vue"),
    meta: { title: "Kiosk", kiosk: true },
  },
];

export const router = createRouter({
  history: createWebHistory(),
  routes,
});

router.beforeEach(async (to) => {
  if (to.name === "print" || to.name === "kiosk") {
    const station = useStationAuth();
    await station.restore();
    if (station.error || (station.required && !station.station)) return { path: "/login", query: { redirect: to.fullPath } };
  }
  const auth = useAuth();
  auth.load();
  if (to.meta.requiresAdmin && !auth.isAuthenticated) {
    return {
      path: "/admin/login",
      query: { redirect: to.fullPath },
    };
  }
  if (to.name === "admin-login" && auth.isAuthenticated) {
    return (to.query.redirect as string) || "/admin";
  }
});

router.afterEach((to) => {
  const t = (to.meta?.title as string | undefined) ?? "TDS Printer";
  document.title = `${t} — TDS Printer`;
});
