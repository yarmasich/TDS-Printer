import { createRouter, createWebHistory, type RouteRecordRaw } from "vue-router";

const routes: RouteRecordRaw[] = [
  {
    path: "/",
    name: "print",
    component: () => import("@/pages/PrintPanel.vue"),
    meta: { title: "Print" },
  },
  {
    path: "/admin",
    name: "admin",
    component: () => import("@/pages/Admin.vue"),
    meta: { title: "Admin" },
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

router.afterEach((to) => {
  const t = (to.meta?.title as string | undefined) ?? "TDS Printer";
  document.title = `${t} — TDS Printer`;
});
