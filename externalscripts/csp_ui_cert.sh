#!/bin/sh
# Read local portal PEM on Zabbix server/proxy; requires openssl and POSIX tools.
# Usage: csp_ui_cert.sh <cert_file_or_path> [cert_dir]

set -eu

CERT_ARG="${1:-}"
CERT_DIR="${2:-/var/lib/zabbix/ssl/certs}"

if [ -z "$CERT_ARG" ]; then
	echo "Usage: $0 <cert_file_or_path> [cert_dir]" >&2
	exit 1
fi

if ! command -v openssl >/dev/null 2>&1; then
	echo "openssl not found" >&2
	exit 1
fi

json_escape() {
	printf '%s' "$1" | sed \
		-e 's/\\/\\\\/g' \
		-e 's/"/\\"/g' \
		-e 's/	/\\t/g'
}

# "Mar 11 13:15:40 2026 GMT" or "2026-03-11T13:15:40Z" / "2026-03-11 13:15:40Z" -> unix (UTC)
asn1_to_unix() {
	_asn1=$1

	# ISO (OpenSSL -dateopt iso_8601): with T or space before time, optional trailing Z
	case "$_asn1" in
		[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]*)
			_iso=$(printf '%s' "$_asn1" | sed 's/[Zz]$//; s/T/ /')
			_date=$(printf '%s' "$_iso" | cut -d' ' -f1)
			_hms=$(printf '%s' "$_iso" | cut -d' ' -f2)
			_year=$(printf '%s' "$_date" | cut -d- -f1)
			_mon=$(printf '%s' "$_date" | cut -d- -f2 | sed 's/^0*\([0-9]\)/\1/; s/^$/0/')
			_day=$(printf '%s' "$_date" | cut -d- -f3 | sed 's/^0*\([0-9]\)/\1/; s/^$/0/')
			_hh=$(printf '%s' "$_hms" | cut -d: -f1 | sed 's/^0*\([0-9]\)/\1/; s/^$/0/')
			_mm=$(printf '%s' "$_hms" | cut -d: -f2 | sed 's/^0*\([0-9]\)/\1/; s/^$/0/')
			_ss=$(printf '%s' "$_hms" | cut -d: -f3 | sed 's/^0*\([0-9]\)/\1/; s/^$/0/' | cut -d. -f1)
			_civil_to_unix "$_year" "$_mon" "$_day" "$_hh" "$_mm" "$_ss"
			return $?
			;;
	esac

	# GNU date
	if _ts=$(date -u -d "$_asn1" +%s 2>/dev/null); then
		printf '%s' "$_ts"
		return 0
	fi
	# BusyBox: strip timezone name, parse fixed format
	_stripped=$(printf '%s' "$_asn1" | sed 's/ GMT$//; s/ UTC$//')
	if _ts=$(date -u -D '%b %d %H:%M:%S %Y' -d "$_stripped" +%s 2>/dev/null); then
		printf '%s' "$_ts"
		return 0
	fi

	# Portable OpenSSL text form: Mon DD HH:MM:SS YYYY GMT
	_mon_name=$(printf '%s' "$_asn1" | awk '{print $1}')
	_day=$(printf '%s' "$_asn1" | awk '{print $2+0}')
	_hms=$(printf '%s' "$_asn1" | awk '{print $3}')
	_year=$(printf '%s' "$_asn1" | awk '{print $4}')
	case "$_mon_name" in
		Jan) _mon=1 ;; Feb) _mon=2 ;; Mar) _mon=3 ;; Apr) _mon=4 ;;
		May) _mon=5 ;; Jun) _mon=6 ;; Jul) _mon=7 ;; Aug) _mon=8 ;;
		Sep) _mon=9 ;; Oct) _mon=10 ;; Nov) _mon=11 ;; Dec) _mon=12 ;;
		*) echo "cannot parse date: $_asn1" >&2; return 1 ;;
	esac
	_hh=$(printf '%s' "$_hms" | cut -d: -f1 | sed 's/^0*\([0-9]\)/\1/; s/^$/0/')
	_mm=$(printf '%s' "$_hms" | cut -d: -f2 | sed 's/^0*\([0-9]\)/\1/; s/^$/0/')
	_ss=$(printf '%s' "$_hms" | cut -d: -f3 | sed 's/^0*\([0-9]\)/\1/; s/^$/0/')
	_civil_to_unix "$_year" "$_mon" "$_day" "$_hh" "$_mm" "$_ss"
}

# Howard Hinnant days_from_civil -> unix (UTC), POSIX sh
_civil_to_unix() {
	_y=$1; _m=$2; _d=$3; _hh=$4; _mi=$5; _ss=$6
	if [ "$_m" -le 2 ]; then
		_y=$((_y - 1))
		_adj=9
	else
		_adj=-3
	fi
	if [ "$_y" -ge 0 ]; then
		_era=$((_y / 400))
	else
		_era=$(( (_y - 399) / 400 ))
	fi
	_yoe=$((_y - _era * 400))
	_doy=$(( (153 * (_m + _adj) + 2) / 5 + _d - 1 ))
	_doe=$((_yoe * 365 + _yoe / 4 - _yoe / 100 + _doy))
	_z=$((_era * 146097 + _doe - 719468))
	printf '%s' "$((_z * 86400 + _hh * 3600 + _mi * 60 + _ss))"
}

cert_not_after_raw() {
	# Prefer ISO (OpenSSL 3); fallback classic text
	if _line=$(openssl x509 -in "$1" -noout -enddate -dateopt iso_8601 2>/dev/null); then
		printf '%s' "${_line#notAfter=}"
		return 0
	fi
	_line=$(openssl x509 -in "$1" -noout -enddate)
	printf '%s' "${_line#notAfter=}"
}

cert_not_before_raw() {
	if _line=$(openssl x509 -in "$1" -noout -startdate -dateopt iso_8601 2>/dev/null); then
		printf '%s' "${_line#notBefore=}"
		return 0
	fi
	_line=$(openssl x509 -in "$1" -noout -startdate)
	printf '%s' "${_line#notBefore=}"
}

# Resolve path: absolute as-is; otherwise CERT_DIR/name; also try basename-only under CERT_DIR
resolve_cert() {
	_arg=$1
	_dir=$2
	case "$_arg" in
		/*)
			printf '%s' "$_arg"
			return 0
			;;
	esac
	if [ -f "${_dir}/${_arg}" ]; then
		printf '%s' "${_dir}/${_arg}"
		return 0
	fi
	# if macro accidentally includes "certs/" prefix
	if [ -f "${_dir}/${_arg#certs/}" ]; then
		printf '%s' "${_dir}/${_arg#certs/}"
		return 0
	fi
	printf '%s' "${_dir}/${_arg}"
}

CERT_PATH=$(resolve_cert "$CERT_ARG" "$CERT_DIR")

if [ ! -f "$CERT_PATH" ]; then
	echo "Certificate file not found: ${CERT_PATH} (arg=${CERT_ARG}, dir=${CERT_DIR})" >&2
	exit 1
fi

if ! openssl x509 -in "$CERT_PATH" -noout >/dev/null 2>&1; then
	echo "File is not a readable X.509 certificate: ${CERT_PATH}" >&2
	exit 1
fi

NOT_BEFORE_ASN1=$(cert_not_before_raw "$CERT_PATH")
NOT_AFTER_ASN1=$(cert_not_after_raw "$CERT_PATH")
ISSUER=$(openssl x509 -in "$CERT_PATH" -noout -issuer | sed 's/^issuer=//')
SUBJECT=$(openssl x509 -in "$CERT_PATH" -noout -subject | sed 's/^subject=//')
FINGERPRINT=$(openssl x509 -in "$CERT_PATH" -noout -fingerprint -sha1 | sed -E 's/^[^=]+=//; s/://g' | tr 'A-F' 'a-f')

NOT_BEFORE_TS=$(asn1_to_unix "$NOT_BEFORE_ASN1")
NOT_AFTER_TS=$(asn1_to_unix "$NOT_AFTER_ASN1")
NOW_TS=$(date +%s)

EXPIRED=0
NOT_YET=0
if [ "$NOT_AFTER_TS" -lt "$NOW_TS" ]; then
	EXPIRED=1
fi
if [ "$NOT_BEFORE_TS" -gt "$NOW_TS" ]; then
	NOT_YET=1
fi

SELF_SIGNED=0
if [ "$ISSUER" = "$SUBJECT" ]; then
	SELF_SIGNED=1
fi

# Optional: verify against Zabbix ssl_ca dir (same tree as certs/)
CA_DIR=$(dirname "$CERT_DIR")/ssl_ca
VERIFY_OK=0
if [ -d "$CA_DIR" ] && ls "$CA_DIR"/* >/dev/null 2>&1; then
	if openssl verify -CApath "$CA_DIR" "$CERT_PATH" >/dev/null 2>&1; then
		VERIFY_OK=1
	fi
fi
# Also try system trust / no CA
if [ "$VERIFY_OK" -eq 0 ]; then
	if openssl verify "$CERT_PATH" >/dev/null 2>&1; then
		VERIFY_OK=1
	fi
fi

RESULT_VALUE="valid"
RESULT_MESSAGE="certificate file ok (${CERT_PATH})"

if [ "$EXPIRED" -eq 1 ]; then
	RESULT_VALUE="invalid"
	RESULT_MESSAGE="certificate has expired (${CERT_PATH})"
elif [ "$NOT_YET" -eq 1 ]; then
	RESULT_VALUE="invalid"
	RESULT_MESSAGE="certificate is not yet valid (${CERT_PATH})"
elif [ "$SELF_SIGNED" -eq 1 ]; then
	RESULT_VALUE="valid-but-self-signed"
	RESULT_MESSAGE="certificate is self-signed (${CERT_PATH})"
elif [ "$VERIFY_OK" -eq 0 ]; then
	# File parseable and in date range, but CA not trusted on this host —
	# treat as valid for expiry monitoring; mark message for diagnostics.
	RESULT_VALUE="valid"
	RESULT_MESSAGE="certificate dates ok, CA not verified (${CERT_PATH})"
else
	RESULT_VALUE="valid"
	RESULT_MESSAGE="certificate verifies successfully (${CERT_PATH})"
fi

ISSUER_J=$(json_escape "$ISSUER")
SUBJECT_J=$(json_escape "$SUBJECT")
MSG_J=$(json_escape "$RESULT_MESSAGE")
ASN1_J=$(json_escape "$NOT_AFTER_ASN1")
PATH_J=$(json_escape "$CERT_PATH")

printf '%s' "{\"result\":{\"value\":\"${RESULT_VALUE}\",\"message\":\"${MSG_J}\"},\"x509\":{\"issuer\":\"${ISSUER_J}\",\"subject\":\"${SUBJECT_J}\",\"not_after\":{\"timestamp\":${NOT_AFTER_TS},\"value\":\"${ASN1_J}\"},\"not_before\":{\"timestamp\":${NOT_BEFORE_TS}}},\"sha1_fingerprint\":\"${FINGERPRINT}\",\"cert_path\":\"${PATH_J}\"}"
printf '\n'
