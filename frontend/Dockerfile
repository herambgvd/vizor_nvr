# =============================================================================
# GVD NVR — Frontend Dockerfile
# =============================================================================

FROM node:20-alpine AS builder

WORKDIR /app

# Install dependencies
# --legacy-peer-deps tolerates React 19 peer mismatches in
# @rjsf and a few other shadcn-adjacent packages until upstreams catch up.
COPY package.json package-lock.json* yarn.lock* ./
RUN npm ci --quiet --legacy-peer-deps

# Build
COPY . .
ARG REACT_APP_API_URL=http://localhost:8000/api
ARG REACT_APP_WS_URL=ws://localhost:8000/api/ws
ARG REACT_APP_GO2RTC_URL=http://localhost:1984
ENV REACT_APP_API_URL=$REACT_APP_API_URL
ENV REACT_APP_WS_URL=$REACT_APP_WS_URL
ENV REACT_APP_GO2RTC_URL=$REACT_APP_GO2RTC_URL
RUN npm run build


# =============================================================================
# Serve with nginx
# =============================================================================
FROM nginx:1.27-alpine

COPY --from=builder /app/build /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s CMD wget -q -O- http://localhost/health || exit 1

CMD ["nginx", "-g", "daemon off;"]
