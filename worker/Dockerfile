FROM node:24-bookworm-slim
WORKDIR /app
ENV NODE_ENV=production
ENV PORT=8080
COPY package.json package-lock.json ./
RUN npm ci --omit=dev && npm cache clean --force
COPY --chown=node:node src ./src
USER node
EXPOSE 8080
CMD ["npm", "start"]
