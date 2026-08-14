# inscode2api — Alpine 运行时镜像
#
# 纯 Python 标准库实现，零第三方依赖：基础镜像只需 python3，镜像体积小。
#
# 构建：  docker build -t inscode2api .
# 运行：  docker run -d --name inscode2api -p 8000:8000 \
#           -v <InsCode 配置目录>:/data/inscode inscode2api
#         （<InsCode 配置目录> 指向桌面端 inscode 生成的 ~/.config/inscode）

FROM alpine:3.20

# 安装 Python 3（本项目零第三方依赖，仅需解释器）
RUN apk add --no-cache python3 \
    && ln -s /usr/bin/python3 /usr/local/bin/python

# 应用代码
WORKDIR /app
COPY config.py signer.py upstream.py server.py oai.py ./

# 持久化存储：挂载桌面端 InsCode 生成的配置目录（taotoken.json 等）
ENV INCODE2API_CONFIG_DIR=/data/inscode
# 容器内需监听 0.0.0.0 才能对外提供服务（默认 127.0.0.1 只在容器内可见）
ENV INCODE2API_HOST=0.0.0.0
ENV INCODE2API_PORT=8000

EXPOSE 8000
VOLUME ["/data/inscode"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3).status==200 else 1)" || exit 1

CMD ["python", "server.py"]
