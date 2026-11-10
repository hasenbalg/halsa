FROM alpine:3.22
RUN apk add --no-cache tor tini
# the alpine tor package already ships a 'tor' user; just own the data dir
RUN mkdir -p /var/lib/tor && chown -R tor:tor /var/lib/tor
COPY entrypoint.sh /entrypoint.sh
RUN chmod 755 /entrypoint.sh
USER tor
ENTRYPOINT ["/sbin/tini", "--", "/entrypoint.sh"]
