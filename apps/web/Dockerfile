# Local Compose development server only; see the deployment plan for production serving.
FROM node:22-bookworm-slim
WORKDIR /app
COPY package.json package-lock.json ./
COPY apps/web/package.json ./apps/web/package.json
RUN npm ci
COPY apps/web ./apps/web
ENV FOODBRIDGE_API_PROXY_TARGET=http://api:8000
EXPOSE 5173
CMD ["npm", "run", "dev", "--workspace", "@foodbridge/web", "--", "--host", "0.0.0.0"]
