export type CropRegion = {
  x: number;
  y: number;
  width: number;
  height: number;
};

export type InvoiceAsset = {
  src: string;
  width: number;
  height: number;
  lineRegions: Record<string, CropRegion>;
};

export const hengweiReviewAssetUrls = {
  bundle: new URL("../../../../docs/suppliers/hengweicraft/supplier_bundle.json", import.meta.url).href,
  profile: new URL("../../../../docs/suppliers/hengweicraft/supplier_profile.json", import.meta.url).href,
  catalogProducts: new URL("../../../../docs/suppliers/hengweicraft/catalog_products.json", import.meta.url).href,
  productCandidates: new URL("../../../../docs/suppliers/hengweicraft/product_candidates.json", import.meta.url).href,
  orders: {
    "364-365": new URL("../../../../docs/suppliers/hengweicraft/orders/364-365.json", import.meta.url).href,
    "369": new URL("../../../../docs/suppliers/hengweicraft/orders/369.json", import.meta.url).href,
  },
} as const;

const order364365LineRegions: Record<string, CropRegion> = {
  "364-365:1": { x: 92, y: 488, width: 192, height: 116 },
  "364-365:2": { x: 92, y: 610, width: 192, height: 116 },
  "364-365:3": { x: 92, y: 732, width: 192, height: 116 },
  "364-365:4": { x: 92, y: 854, width: 192, height: 116 },
  "364-365:5": { x: 92, y: 976, width: 192, height: 116 },
  "364-365:6": { x: 92, y: 1098, width: 192, height: 116 },
  "364-365:7": { x: 92, y: 1220, width: 192, height: 116 },
  "364-365:8": { x: 92, y: 1342, width: 192, height: 168 },
  "364-365:9": { x: 92, y: 1518, width: 192, height: 232 },
  "364-365:10": { x: 92, y: 1760, width: 192, height: 198 },
  "364-365:11": { x: 92, y: 1988, width: 192, height: 226 },
  "364-365:12": { x: 92, y: 2250, width: 192, height: 116 },
  "364-365:13": { x: 92, y: 2372, width: 192, height: 116 },
  "364-365:14": { x: 92, y: 2494, width: 192, height: 116 },
  "364-365:15": { x: 92, y: 2616, width: 192, height: 116 },
  "364-365:16": { x: 92, y: 2834, width: 192, height: 116 },
  "364-365:17": { x: 92, y: 2956, width: 192, height: 116 },
};

const order369LineRegions: Record<string, CropRegion> = {
  "369:1": { x: 92, y: 452, width: 176, height: 82 },
  "369:2": { x: 92, y: 536, width: 176, height: 94 },
  "369:3": { x: 92, y: 536, width: 176, height: 94 },
  "369:4": { x: 92, y: 536, width: 176, height: 94 },
  "369:5": { x: 92, y: 636, width: 176, height: 94 },
  "369:7": { x: 92, y: 734, width: 176, height: 94 },
  "369:9": { x: 92, y: 832, width: 176, height: 94 },
  "369:10:a": { x: 92, y: 930, width: 176, height: 94 },
  "369:10:b": { x: 92, y: 930, width: 176, height: 94 },
  "369:11": { x: 92, y: 1028, width: 176, height: 94 },
  "369:12": { x: 92, y: 1126, width: 176, height: 144 },
  "369:13": { x: 92, y: 1126, width: 176, height: 144 },
  "369:14": { x: 92, y: 1126, width: 176, height: 144 },
  "369:15": { x: 92, y: 1126, width: 176, height: 144 },
  "369:16": { x: 92, y: 1276, width: 176, height: 94 },
  "369:17": { x: 92, y: 1374, width: 176, height: 94 },
  "369:18": { x: 92, y: 1472, width: 176, height: 144 },
  "369:19": { x: 92, y: 1472, width: 176, height: 144 },
  "369:20": { x: 92, y: 1472, width: 176, height: 144 },
  "369:21": { x: 92, y: 1622, width: 176, height: 94 },
  "369:23": { x: 92, y: 1720, width: 176, height: 94 },
  "369:26": { x: 92, y: 1818, width: 176, height: 94 },
  "369:27": { x: 92, y: 1916, width: 176, height: 94 },
  "369:28": { x: 92, y: 2014, width: 176, height: 94 },
};

export const hengweiInvoiceAssets: Record<string, InvoiceAsset> = {
  "364-365": {
    src: new URL(
      "../../../../docs/suppliers/hengweicraft/orders/order-364-365-2026-03-26-source.PNG",
      import.meta.url,
    ).href,
    width: 1056,
    height: 4026,
    lineRegions: order364365LineRegions,
  },
  "369": {
    src: new URL(
      "../../../../docs/suppliers/hengweicraft/orders/order-149-2025-01-15-source.PNG",
      import.meta.url,
    ).href,
    width: 975,
    height: 2222,
    lineRegions: order369LineRegions,
  },
};
